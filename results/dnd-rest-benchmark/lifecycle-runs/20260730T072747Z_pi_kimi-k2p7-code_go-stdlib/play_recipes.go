package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sort"
)

// recipeResponse is the exact recipe object returned by the API.
type recipeResponse struct {
	RecipeID       string          `json:"recipe_id"`
	Name           string          `json:"name"`
	Ingredients    json.RawMessage `json:"ingredients"`
	OutputItem     string          `json:"output_item"`
	OutputQuantity int             `json:"output_quantity"`
}

// recipeCreateRequest binds the POST /recipes payload.
type recipeCreateRequest struct {
	RecipeID       string         `json:"recipe_id"`
	Name           string         `json:"name"`
	Ingredients    map[string]int `json:"ingredients"`
	OutputItem     string         `json:"output_item"`
	OutputQuantity int            `json:"output_quantity"`
}

// recipesListResponse is the shape returned by GET /recipes.
type recipesListResponse struct {
	Recipes []recipeResponse `json:"recipes"`
}

// craftRequest binds the POST /recipes/{recipe_id}/craft payload.
type craftRequest struct {
	CharacterID string `json:"character_id"`
}

// craftResponse is the shape returned after a successful craft.
type craftResponse struct {
	CharacterID    string `json:"character_id"`
	RecipeID       string `json:"recipe_id"`
	OutputItem     string `json:"output_item"`
	OutputQuantity int    `json:"output_quantity"`
}

// recipeInternal is the parsed recipe loaded from the database.
type recipeInternal struct {
	RecipeID       string
	Name           string
	Ingredients    map[string]int
	IngredientsRaw string
	OutputItem     string
	OutputQuantity int
}

// validateRecipeCreateRequest checks the recipe creation payload. It returns
// a non-empty error message if any constraint fails.
func validateRecipeCreateRequest(req *recipeCreateRequest) string {
	if req.RecipeID == "" || req.Name == "" {
		return "invalid recipe"
	}
	if len(req.Ingredients) == 0 {
		return "invalid recipe"
	}
	for itemID, qty := range req.Ingredients {
		if !validInventoryItemIDs[itemID] || qty <= 0 {
			return "invalid recipe"
		}
	}
	if !validInventoryItemIDs[req.OutputItem] {
		return "invalid recipe"
	}
	if req.OutputQuantity <= 0 {
		return "invalid recipe"
	}
	return ""
}

// canonicalIngredientsJSON returns a deterministic JSON object string for the
// ingredient map by emitting keys in sorted order.
func canonicalIngredientsJSON(ingredients map[string]int) (string, error) {
	keys := make([]string, 0, len(ingredients))
	for k := range ingredients {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	out := []byte{'{'}
	for i, k := range keys {
		if i > 0 {
			out = append(out, ',')
		}
		kb, err := json.Marshal(k)
		if err != nil {
			return "", err
		}
		vb, err := json.Marshal(ingredients[k])
		if err != nil {
			return "", err
		}
		out = append(out, kb...)
		out = append(out, ':')
		out = append(out, vb...)
	}
	out = append(out, '}')
	return string(out), nil
}

// queryRecipe loads a recipe by campaign and recipe id. The caller must hold
// dbMu.
func queryRecipe(campaignID, recipeID string) (*recipeInternal, bool, error) {
	var rows []struct {
		RecipeID       string `json:"recipe_id"`
		Name           string `json:"name"`
		Ingredients    string `json:"ingredients"`
		OutputItem     string `json:"output_item"`
		OutputQuantity int    `json:"output_quantity"`
	}
	sql := fmt.Sprintf("SELECT recipe_id, name, ingredients, output_item, output_quantity FROM campaign_recipes WHERE campaign_id=%s AND recipe_id=%s LIMIT 1;", sq(campaignID), sq(recipeID))
	if err := queryRows(sql, &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	var ingredients map[string]int
	if err := json.Unmarshal([]byte(rows[0].Ingredients), &ingredients); err != nil {
		return nil, false, err
	}
	return &recipeInternal{
		RecipeID:       rows[0].RecipeID,
		Name:           rows[0].Name,
		Ingredients:    ingredients,
		IngredientsRaw: rows[0].Ingredients,
		OutputItem:     rows[0].OutputItem,
		OutputQuantity: rows[0].OutputQuantity,
	}, true, nil
}

// queryRecipeExists reports whether a recipe with the given id exists in a
// campaign. The caller must hold dbMu.
func queryRecipeExists(campaignID, recipeID string) (bool, error) {
	return queryExists(fmt.Sprintf("SELECT 1 FROM campaign_recipes WHERE campaign_id=%s AND recipe_id=%s LIMIT 1;", sq(campaignID), sq(recipeID)))
}

// queryCampaignRecipes loads all recipes for a campaign in creation order. The
// caller must hold dbMu.
func queryCampaignRecipes(campaignID string) ([]recipeResponse, error) {
	var rows []struct {
		RecipeID       string `json:"recipe_id"`
		Name           string `json:"name"`
		Ingredients    string `json:"ingredients"`
		OutputItem     string `json:"output_item"`
		OutputQuantity int    `json:"output_quantity"`
	}
	sql := fmt.Sprintf("SELECT recipe_id, name, ingredients, output_item, output_quantity FROM campaign_recipes WHERE campaign_id=%s ORDER BY id;", sq(campaignID))
	if err := queryRows(sql, &rows); err != nil {
		return nil, err
	}
	recipes := make([]recipeResponse, 0, len(rows))
	for _, row := range rows {
		recipes = append(recipes, recipeResponse{
			RecipeID:       row.RecipeID,
			Name:           row.Name,
			Ingredients:    json.RawMessage(row.Ingredients),
			OutputItem:     row.OutputItem,
			OutputQuantity: row.OutputQuantity,
		})
	}
	return recipes, nil
}

// createRecipeHandler creates a new recipe for a campaign. Only the campaign
// DM may create recipes; players receive 403.
func createRecipeHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requireDM(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("recipe create campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if campaign.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req recipeCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if msg := validateRecipeCreateRequest(&req); msg != "" {
		writeError(w, http.StatusBadRequest, msg)
		return
	}

	dup, err := queryRecipeExists(campaignID, req.RecipeID)
	if err != nil {
		log.Printf("recipe duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dup {
		writeError(w, http.StatusConflict, "recipe already exists")
		return
	}

	ingredientsJSON, err := canonicalIngredientsJSON(req.Ingredients)
	if err != nil {
		log.Printf("recipe ingredients marshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	insertSQL := fmt.Sprintf("INSERT INTO campaign_recipes (campaign_id, recipe_id, name, ingredients, output_item, output_quantity) VALUES (%s, %s, %s, %s, %s, %d);",
		sq(campaignID), sq(req.RecipeID), sq(req.Name), sq(ingredientsJSON), sq(req.OutputItem), req.OutputQuantity)
	if err := dbExec(insertSQL); err != nil {
		log.Printf("recipe insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, recipeResponse{
		RecipeID:       req.RecipeID,
		Name:           req.Name,
		Ingredients:    json.RawMessage(ingredientsJSON),
		OutputItem:     req.OutputItem,
		OutputQuantity: req.OutputQuantity,
	})
}

// listRecipesHandler lists all recipes for a campaign. Authenticated campaign
// members may list recipes.
func listRecipesHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	_, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("recipes list campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	recipes, err := queryCampaignRecipes(campaignID)
	if err != nil {
		log.Printf("recipes list query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if recipes == nil {
		recipes = []recipeResponse{}
	}

	writeJSON(w, http.StatusOK, recipesListResponse{Recipes: recipes})
}

// craftRecipeHandler lets a character craft an item using a recipe. Only the
// player who owns the character may craft; the DM and non-owners receive 403.
func craftRecipeHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requirePlayer(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")
	recipeID := r.PathValue("recipe_id")

	_, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("recipe craft campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	recipe, ok, err := queryRecipe(campaignID, recipeID)
	if err != nil {
		log.Printf("recipe craft query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "recipe not found")
		return
	}

	var req craftRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CharacterID == "" {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, req.CharacterID)
	if err != nil {
		log.Printf("recipe craft member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if member.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	// Verify all ingredients are available before mutating any state.
	for itemID, needed := range recipe.Ingredients {
		held, err := queryCharacterInventoryItemQuantity(campaignID, req.CharacterID, itemID)
		if err != nil {
			log.Printf("recipe craft held query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if held < needed {
			writeError(w, http.StatusConflict, "insufficient ingredients")
			return
		}
	}

	// Build the atomic transaction: consume each ingredient, then upsert the
	// output item.
	var txParts string
	for itemID, needed := range recipe.Ingredients {
		held, _ := queryCharacterInventoryItemQuantity(campaignID, req.CharacterID, itemID)
		remaining := held - needed
		if remaining == 0 {
			txParts += fmt.Sprintf("DELETE FROM character_inventory_items WHERE campaign_id=%s AND character_id=%s AND item_id=%s;",
				sq(campaignID), sq(req.CharacterID), sq(itemID))
		} else {
			txParts += fmt.Sprintf("UPDATE character_inventory_items SET quantity=%d WHERE campaign_id=%s AND character_id=%s AND item_id=%s;",
				remaining, sq(campaignID), sq(req.CharacterID), sq(itemID))
		}
	}
	txParts += fmt.Sprintf("INSERT INTO character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (%s, %s, %s, %d) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity;",
		sq(campaignID), sq(req.CharacterID), sq(recipe.OutputItem), recipe.OutputQuantity)

	if err := dbExec("BEGIN; " + txParts + " COMMIT;"); err != nil {
		log.Printf("recipe craft transaction error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, craftResponse{
		CharacterID:    req.CharacterID,
		RecipeID:       recipe.RecipeID,
		OutputItem:     recipe.OutputItem,
		OutputQuantity: recipe.OutputQuantity,
	})
}
