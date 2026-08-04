package main

import (
	"net/http"
	"sync"
)

// playRecipe is a DM-created crafting recipe with deterministic ingredient
// requirements backed by the campaign inventory item catalog.
type playRecipe struct {
	CampaignID     string
	RecipeID       string
	Name           string
	Ingredients    map[string]int
	OutputItem     string
	OutputQuantity int
}

// campaignRecipesMu guards campaignRecipes, the in-memory index mirroring the
// play_recipes table. Keyed by campaign id, holding recipes in creation
// order.
var (
	campaignRecipesMu sync.Mutex
	campaignRecipes   = map[string][]*playRecipe{}
)

// findRecipe returns the recipe with the given id within campaignID, or nil.
// Callers must already hold campaignRecipesMu.
func findRecipe(campaignID, recipeID string) *playRecipe {
	for _, rec := range campaignRecipes[campaignID] {
		if rec.RecipeID == recipeID {
			return rec
		}
	}
	return nil
}

// recipeJSON renders rec as its exact API shape.
func recipeJSON(rec *playRecipe) map[string]any {
	return map[string]any{
		"recipe_id":       rec.RecipeID,
		"name":            rec.Name,
		"ingredients":     rec.Ingredients,
		"output_item":     rec.OutputItem,
		"output_quantity": rec.OutputQuantity,
	}
}

// validRecipeIngredients reports whether ingredients is a nonempty map of
// valid catalog item ids to positive integer quantities.
func validRecipeIngredients(ingredients map[string]int) bool {
	if len(ingredients) == 0 {
		return false
	}
	for itemID, qty := range ingredients {
		if !inventoryCatalog[itemID] {
			return false
		}
		if qty <= 0 {
			return false
		}
	}
	return true
}

type recipeRequest struct {
	RecipeID       string         `json:"recipe_id"`
	Name           string         `json:"name"`
	Ingredients    map[string]int `json:"ingredients"`
	OutputItem     string         `json:"output_item"`
	OutputQuantity int            `json:"output_quantity"`
}

// createRecipeHandler lets the campaign's owning dm create a new crafting
// recipe.
func createRecipeHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req recipeRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may create recipes")
		return
	}

	if req.RecipeID == "" || req.Name == "" || !validRecipeIngredients(req.Ingredients) ||
		!inventoryCatalog[req.OutputItem] || req.OutputQuantity <= 0 {
		writeError(w, http.StatusBadRequest, "recipe_id and name are required nonempty strings, ingredients must be a nonempty map of valid item ids to positive quantities, output_item must be a valid item id, and output_quantity must be positive")
		return
	}

	campaignRecipesMu.Lock()
	defer campaignRecipesMu.Unlock()

	if findRecipe(campaignID, req.RecipeID) != nil {
		writeError(w, http.StatusConflict, "recipe_id already exists in this campaign")
		return
	}

	ingredients := make(map[string]int, len(req.Ingredients))
	for itemID, qty := range req.Ingredients {
		ingredients[itemID] = qty
	}

	rec := &playRecipe{
		CampaignID:     campaignID,
		RecipeID:       req.RecipeID,
		Name:           req.Name,
		Ingredients:    ingredients,
		OutputItem:     req.OutputItem,
		OutputQuantity: req.OutputQuantity,
	}
	if err := saveRecipeToDB(rec); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save recipe")
		return
	}
	campaignRecipes[campaignID] = append(campaignRecipes[campaignID], rec)

	writeJSON(w, http.StatusCreated, recipeJSON(rec))
}

// listRecipesHandler returns all recipes for a campaign in creation order.
// Any authenticated campaign member (dm or player) may list recipes.
func listRecipesHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be the dm or a member of this campaign")
		return
	}

	campaignRecipesMu.Lock()
	defer campaignRecipesMu.Unlock()

	recipes := campaignRecipes[campaignID]
	out := make([]map[string]any, 0, len(recipes))
	for _, rec := range recipes {
		out = append(out, recipeJSON(rec))
	}

	writeJSON(w, http.StatusOK, map[string]any{"recipes": out})
}

type craftRecipeRequest struct {
	CharacterID string `json:"character_id"`
}

// craftRecipeHandler lets a character's owner craft a recipe, atomically
// consuming the required ingredients and adding the output item.
func craftRecipeHandler(w http.ResponseWriter, r *http.Request, campaignID, recipeID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req craftRecipeRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	campaignRecipesMu.Lock()
	defer campaignRecipesMu.Unlock()

	rec := findRecipe(campaignID, recipeID)
	if rec == nil {
		writeError(w, http.StatusNotFound, "unknown recipe id")
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, req.CharacterID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if actor.Username == c.Owner {
		writeError(w, http.StatusForbidden, "the dm may not craft recipes")
		return
	}
	if actor.Username != playMemberOwner(member) {
		writeError(w, http.StatusForbidden, "only the character's owner may craft")
		return
	}

	inventoryItemsMu.Lock()
	defer inventoryItemsMu.Unlock()

	for itemID, qty := range rec.Ingredients {
		held := 0
		if inventoryItems[campaignID] != nil && inventoryItems[campaignID][req.CharacterID] != nil {
			if item, ok := inventoryItems[campaignID][req.CharacterID][itemID]; ok {
				held = item.Quantity
			}
		}
		if held < qty {
			writeError(w, http.StatusConflict, "insufficient ingredients")
			return
		}
	}

	for itemID, qty := range rec.Ingredients {
		item := inventoryItems[campaignID][req.CharacterID][itemID]
		item.Quantity -= qty
		if item.Quantity <= 0 {
			if err := deleteInventoryItemFromDB(campaignID, req.CharacterID, itemID); err != nil {
				writeError(w, http.StatusInternalServerError, "failed to remove inventory item")
				return
			}
			delete(inventoryItems[campaignID][req.CharacterID], itemID)
		} else {
			if err := saveInventoryItemToDB(item); err != nil {
				writeError(w, http.StatusInternalServerError, "failed to save inventory item")
				return
			}
		}
	}

	if inventoryItems[campaignID] == nil {
		inventoryItems[campaignID] = map[string]map[string]*playInventoryItem{}
	}
	if inventoryItems[campaignID][req.CharacterID] == nil {
		inventoryItems[campaignID][req.CharacterID] = map[string]*playInventoryItem{}
	}
	outItem, exists := inventoryItems[campaignID][req.CharacterID][rec.OutputItem]
	if !exists {
		outItem = &playInventoryItem{CampaignID: campaignID, CharacterID: req.CharacterID, ItemID: rec.OutputItem, Quantity: 0}
		inventoryItems[campaignID][req.CharacterID][rec.OutputItem] = outItem
	}
	outItem.Quantity += rec.OutputQuantity
	if err := saveInventoryItemToDB(outItem); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save inventory item")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"character_id":    req.CharacterID,
		"recipe_id":       rec.RecipeID,
		"output_item":     rec.OutputItem,
		"output_quantity": rec.OutputQuantity,
	})
}
