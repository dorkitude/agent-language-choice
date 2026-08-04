package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// playRecipe is a DM-managed crafting recipe with deterministic ingredient
// requirements, backed by the public campaign inventory item catalog.
type playRecipe struct {
	RecipeID       string
	Name           string
	Ingredients    map[string]int
	OutputItem     string
	OutputQuantity int
}

func playRecipeResponse(rec *playRecipe) map[string]interface{} {
	return map[string]interface{}{
		"recipe_id":       rec.RecipeID,
		"name":            rec.Name,
		"ingredients":     rec.Ingredients,
		"output_item":     rec.OutputItem,
		"output_quantity": rec.OutputQuantity,
	}
}

// handlePlayCampaignRecipeSub routes the "recipes" and "recipes/..."
// sub-paths of a play campaign. It returns false if rest does not name a
// recognized recipe path, so the caller can fall through to its own routing.
func handlePlayCampaignRecipeSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "recipes" {
		switch r.Method {
		case http.MethodPost:
			handleCreatePlayRecipe(w, r, campaignID)
		case http.MethodGet:
			handleListPlayRecipes(w, r, campaignID)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
		return true
	}
	if !strings.HasPrefix(rest, "recipes/") {
		return false
	}
	recipeRest := strings.TrimPrefix(rest, "recipes/")
	if recipeID, ok := strings.CutSuffix(recipeRest, "/craft"); ok && recipeID != "" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handlePlayRecipeCraft(w, r, campaignID, recipeID)
		return true
	}
	return false
}

type playRecipeRequest struct {
	RecipeID       string         `json:"recipe_id"`
	Name           string         `json:"name"`
	Ingredients    map[string]int `json:"ingredients"`
	OutputItem     string         `json:"output_item"`
	OutputQuantity *int           `json:"output_quantity"`
}

// handleCreatePlayRecipe lets the campaign dm create a new crafting recipe.
// Only the dm may call this; unknown campaigns return 404, invalid payloads
// return 400, and duplicate recipe ids within the campaign return 409.
func handleCreatePlayRecipe(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req playRecipeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.RecipeID == "" || req.Name == "" {
		writeError(w, http.StatusBadRequest, "recipe_id and name are required")
		return
	}
	if len(req.Ingredients) == 0 {
		writeError(w, http.StatusBadRequest, "ingredients must be a nonempty object of valid item ids to positive quantities")
		return
	}
	for itemID, qty := range req.Ingredients {
		if !validInventoryItems[itemID] || qty <= 0 {
			writeError(w, http.StatusBadRequest, "ingredients must be a nonempty object of valid item ids to positive quantities")
			return
		}
	}
	if !validInventoryItems[req.OutputItem] {
		writeError(w, http.StatusBadRequest, "output_item must be a valid item id")
		return
	}
	if req.OutputQuantity == nil || *req.OutputQuantity <= 0 {
		writeError(w, http.StatusBadRequest, "output_quantity must be a positive integer")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may create recipes")
		return
	}
	if c.Recipes == nil {
		c.Recipes = make(map[string]*playRecipe)
	}
	if _, exists := c.Recipes[req.RecipeID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "recipe_id already exists")
		return
	}

	ingredients := make(map[string]int, len(req.Ingredients))
	for itemID, qty := range req.Ingredients {
		ingredients[itemID] = qty
	}
	rec := &playRecipe{
		RecipeID:       req.RecipeID,
		Name:           req.Name,
		Ingredients:    ingredients,
		OutputItem:     req.OutputItem,
		OutputQuantity: *req.OutputQuantity,
	}
	c.Recipes[req.RecipeID] = rec
	c.RecipeOrder = append(c.RecipeOrder, req.RecipeID)
	resp := playRecipeResponse(rec)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

// handleListPlayRecipes returns every recipe in campaign creation order.
// Authenticated campaign members (owner or player) may list recipes.
func handleListPlayRecipes(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner or a member may view recipes")
		return
	}

	recipes := make([]map[string]interface{}, 0, len(c.RecipeOrder))
	for _, recipeID := range c.RecipeOrder {
		recipes = append(recipes, playRecipeResponse(c.Recipes[recipeID]))
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{"recipes": recipes})
}

type playRecipeCraftRequest struct {
	CharacterID string `json:"character_id"`
}

// handlePlayRecipeCraft lets a character's owning player craft a recipe,
// atomically consuming ingredients and adding the output item. Only the
// player who owns character_id may craft; the dm and non-owners receive 403.
// Unknown recipes or characters return 404. Insufficient ingredients return
// 409 and must not partially mutate state.
func handlePlayRecipeCraft(w http.ResponseWriter, r *http.Request, campaignID, recipeID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req playRecipeCraftRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CharacterID == "" {
		writeError(w, http.StatusBadRequest, "character_id is required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	rec := c.Recipes[recipeID]
	if rec == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "recipe not found")
		return
	}
	member := findPlayMemberByCharacterID(c, req.CharacterID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if c.Owner == username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "the dm may not craft")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may craft")
		return
	}

	for itemID, qty := range rec.Ingredients {
		if member.Items[itemID] < qty {
			playMu.Unlock()
			writeError(w, http.StatusConflict, "insufficient ingredients")
			return
		}
	}

	for itemID, qty := range rec.Ingredients {
		member.Items[itemID] -= qty
	}
	member.Items[rec.OutputItem] += rec.OutputQuantity

	resp := map[string]interface{}{
		"character_id":    req.CharacterID,
		"recipe_id":       rec.RecipeID,
		"output_item":     rec.OutputItem,
		"output_quantity": rec.OutputQuantity,
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}
