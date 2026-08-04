package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// createPlayRecipeHandler lets a campaign DM create a crafting recipe whose
// ingredients and output are drawn from the public campaign inventory item
// catalog.
func createPlayRecipeHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can create recipes")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can create recipes")
		return
	}

	var req recipe
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	req.RecipeID = strings.TrimSpace(req.RecipeID)
	req.Name = strings.TrimSpace(req.Name)
	req.OutputItem = strings.TrimSpace(req.OutputItem)

	if req.RecipeID == "" {
		badRequest(w, "recipe_id is required")
		return
	}
	if req.Name == "" {
		badRequest(w, "name is required")
		return
	}
	if len(req.Ingredients) == 0 {
		badRequest(w, "ingredients are required")
		return
	}
	for itemID, qty := range req.Ingredients {
		if strings.TrimSpace(itemID) == "" || !validInventoryItemIDs[itemID] {
			badRequest(w, "invalid ingredient item_id")
			return
		}
		if qty <= 0 {
			badRequest(w, "ingredient quantity must be positive")
			return
		}
	}
	if req.OutputItem == "" || !validInventoryItemIDs[req.OutputItem] {
		badRequest(w, "invalid output_item")
		return
	}
	if req.OutputQuantity <= 0 {
		badRequest(w, "output_quantity must be positive")
		return
	}

	if err := dbCreatePlayRecipe(id, req.RecipeID, req.Name, req.Ingredients, req.OutputItem, req.OutputQuantity); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "recipe id already exists")
			return
		}
		log.Printf("create play recipe: %v", err)
		badRequest(w, "failed to create recipe")
		return
	}

	writeJSON(w, http.StatusCreated, recipe{
		RecipeID:       req.RecipeID,
		Name:           req.Name,
		Ingredients:    req.Ingredients,
		OutputItem:     req.OutputItem,
		OutputQuantity: req.OutputQuantity,
	})
}

// listPlayRecipesHandler lets authenticated campaign members list all crafting
// recipes for a campaign in creation order.
func listPlayRecipesHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	recipes, err := dbListPlayRecipes(id)
	if err != nil {
		log.Printf("list play recipes: %v", err)
		badRequest(w, "failed to list recipes")
		return
	}

	writeJSON(w, http.StatusOK, recipesResponse{Recipes: recipes})
}

// craftRecipeHandler lets the owner of a character consume the ingredients for
// a recipe and receive its output item.
func craftRecipeHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role == roleDM {
		forbidden(w, "only players may craft recipes")
		return
	}

	id := r.PathValue("id")
	recipeID := r.PathValue("recipe_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	var req craftRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	req.CharacterID = strings.TrimSpace(req.CharacterID)
	if req.CharacterID == "" {
		notFound(w, "character not found")
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, req.CharacterID)
	if err != nil {
		log.Printf("craft recipe: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != u.Username {
		forbidden(w, "only the character owner may craft")
		return
	}

	resp, err := dbCraftRecipe(id, recipeID, req.CharacterID)
	if err != nil {
		if err == errRecipeNotFound {
			notFound(w, "recipe not found")
			return
		}
		if err == errCharacterNotFound {
			notFound(w, "character not found")
			return
		}
		if err == errInsufficientInventory {
			conflict(w, "insufficient ingredients")
			return
		}
		log.Printf("craft recipe: %v", err)
		badRequest(w, "failed to craft recipe")
		return
	}

	writeJSON(w, http.StatusCreated, resp)
}
