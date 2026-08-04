package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
)

// validateShop validates and normalizes a shop create request. It trims
// whitespace from the shop id and name and enforces the stock, price, and
// catalog rules from the stage contract.
func validateShop(req shopCreateRequest) (shopCreateRequest, error) {
	req.ShopID = strings.TrimSpace(req.ShopID)
	if req.ShopID == "" {
		return req, fmt.Errorf("shop_id is required")
	}
	req.Name = strings.TrimSpace(req.Name)
	if req.Name == "" {
		return req, fmt.Errorf("name is required")
	}
	if len(req.Stock) == 0 {
		return req, fmt.Errorf("stock is required")
	}
	for itemID, quantity := range req.Stock {
		if itemID == "" || !validInventoryItemIDs[itemID] {
			return req, fmt.Errorf("invalid item_id")
		}
		if quantity <= 0 {
			return req, fmt.Errorf("stock quantity must be positive")
		}
	}
	if req.BuyPrice <= 0 {
		return req, fmt.Errorf("buy_price must be positive")
	}
	if req.SellPrice < 0 {
		return req, fmt.Errorf("sell_price must be nonnegative")
	}
	return req, nil
}

func createPlayShopHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can create shops")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can create shops")
		return
	}

	settlementID := r.PathValue("settlement_id")

	var req shopCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	req, err := validateShop(req)
	if err != nil {
		badRequest(w, err.Error())
		return
	}

	if err := dbCreatePlayShop(id, settlementID, req.ShopID, req.Name, req.Stock, req.BuyPrice, req.SellPrice); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "shop id already exists")
			return
		}
		if isForeignKeyViolation(err) {
			notFound(w, "settlement not found")
			return
		}
		log.Printf("create play shop: %v", err)
		badRequest(w, "failed to create shop")
		return
	}

	writeJSON(w, http.StatusCreated, shop{
		ShopID:    req.ShopID,
		Name:      req.Name,
		Stock:     req.Stock,
		BuyPrice:  req.BuyPrice,
		SellPrice: req.SellPrice,
	})
}

func getPlayShopHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	settlementID := r.PathValue("settlement_id")
	shopID := r.PathValue("shop_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	s, err := dbGetPlayShop(id, settlementID, shopID)
	if err != nil {
		log.Printf("get play shop: %v", err)
		badRequest(w, "failed to read shop")
		return
	}
	if s == nil {
		notFound(w, "shop not found")
		return
	}

	if p.Owner != u.Username {
		membership, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
		if err != nil {
			log.Printf("get shop membership: %v", err)
			badRequest(w, "failed to read membership")
			return
		}
		if membership == nil {
			forbidden(w, "not a campaign member")
			return
		}
		discovered, err := dbGetPlaySettlementDiscoveries(id, settlementID)
		if err != nil {
			log.Printf("get shop settlement discoveries: %v", err)
			badRequest(w, "failed to read settlement discoveries")
			return
		}
		found := false
		for _, charID := range discovered {
			if charID == membership.CharacterID {
				found = true
				break
			}
		}
		if !found {
			notFound(w, "shop not found")
			return
		}
	}

	writeJSON(w, http.StatusOK, s)
}

func buyFromPlayShopHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != rolePlayer {
		forbidden(w, "only players may buy from shops")
		return
	}

	id := r.PathValue("id")
	settlementID := r.PathValue("settlement_id")
	shopID := r.PathValue("shop_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	var req shopTransactionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.CharacterID == "" {
		notFound(w, "character not found")
		return
	}
	if !validInventoryItemIDs[req.ItemID] {
		badRequest(w, "invalid item_id")
		return
	}
	if req.Quantity <= 0 {
		badRequest(w, "quantity must be positive")
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, req.CharacterID)
	if err != nil {
		log.Printf("buy from shop: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != u.Username {
		forbidden(w, "only the character owner may buy")
		return
	}

	if s, err := dbGetPlayShop(id, settlementID, shopID); err != nil || s == nil {
		if err != nil {
			log.Printf("buy from shop lookup: %v", err)
			badRequest(w, "failed to read shop")
		} else {
			notFound(w, "shop not found")
		}
		return
	}

	result, err := dbBuyFromShop(id, settlementID, shopID, req.CharacterID, req.ItemID, req.Quantity)
	if err != nil {
		if err == errInsufficientShopStock {
			conflict(w, "insufficient stock")
			return
		}
		if err == errInsufficientGold {
			conflict(w, "insufficient gold")
			return
		}
		log.Printf("buy from shop: %v", err)
		badRequest(w, "failed to buy item")
		return
	}

	writeJSON(w, http.StatusOK, shopTransactionResponse{
		CharacterID: req.CharacterID,
		ItemID:      req.ItemID,
		Quantity:    req.Quantity,
		Gold:        result.newGold,
		Stock:       result.newStock,
	})
}

func sellToPlayShopHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != rolePlayer {
		forbidden(w, "only players may sell to shops")
		return
	}

	id := r.PathValue("id")
	settlementID := r.PathValue("settlement_id")
	shopID := r.PathValue("shop_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	var req shopTransactionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.CharacterID == "" {
		notFound(w, "character not found")
		return
	}
	if !validInventoryItemIDs[req.ItemID] {
		badRequest(w, "invalid item_id")
		return
	}
	if req.Quantity <= 0 {
		badRequest(w, "quantity must be positive")
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, req.CharacterID)
	if err != nil {
		log.Printf("sell to shop: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != u.Username {
		forbidden(w, "only the character owner may sell")
		return
	}

	if s, err := dbGetPlayShop(id, settlementID, shopID); err != nil || s == nil {
		if err != nil {
			log.Printf("sell to shop lookup: %v", err)
			badRequest(w, "failed to read shop")
		} else {
			notFound(w, "shop not found")
		}
		return
	}

	result, err := dbSellToShop(id, settlementID, shopID, req.CharacterID, req.ItemID, req.Quantity)
	if err != nil {
		if err == errInsufficientInventory {
			conflict(w, "insufficient quantity")
			return
		}
		log.Printf("sell to shop: %v", err)
		badRequest(w, "failed to sell item")
		return
	}

	writeJSON(w, http.StatusOK, shopTransactionResponse{
		CharacterID: req.CharacterID,
		ItemID:      req.ItemID,
		Quantity:    req.Quantity,
		Gold:        result.newGold,
		Stock:       result.newStock,
	})
}
