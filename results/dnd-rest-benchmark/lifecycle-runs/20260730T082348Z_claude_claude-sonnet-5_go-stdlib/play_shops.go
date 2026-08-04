package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// playShop is a DM-managed settlement shop with deterministic stock and
// prices, backed by campaign character inventory and currency.
type playShop struct {
	ShopID    string
	Name      string
	Stock     map[string]int
	BuyPrice  int
	SellPrice int
}

func playShopResponse(s *playShop) map[string]interface{} {
	return map[string]interface{}{
		"shop_id":    s.ShopID,
		"name":       s.Name,
		"stock":      s.Stock,
		"buy_price":  s.BuyPrice,
		"sell_price": s.SellPrice,
	}
}

// handlePlaySettlementShopSub routes the "shops" sub-paths of a settlement:
// the shops collection, a single shop, and its buy/sell actions. It returns
// false if shopsRest does not name a recognized shop path, so the caller can
// fall through to its own routing.
func handlePlaySettlementShopSub(w http.ResponseWriter, r *http.Request, campaignID, settlementID, shopsRest string) bool {
	if shopsRest == "" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleCreatePlayShop(w, r, campaignID, settlementID)
		return true
	}
	if !strings.HasPrefix(shopsRest, "/") {
		return false
	}
	shopRest := strings.TrimPrefix(shopsRest, "/")

	if shopID, ok := strings.CutSuffix(shopRest, "/buy"); ok && shopID != "" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handlePlayShopBuy(w, r, campaignID, settlementID, shopID)
		return true
	}
	if shopID, ok := strings.CutSuffix(shopRest, "/sell"); ok && shopID != "" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handlePlayShopSell(w, r, campaignID, settlementID, shopID)
		return true
	}
	if shopRest == "" || strings.Contains(shopRest, "/") {
		return false
	}
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return true
	}
	handleGetPlayShop(w, r, campaignID, settlementID, shopRest)
	return true
}

type playShopRequest struct {
	ShopID    string         `json:"shop_id"`
	Name      string         `json:"name"`
	Stock     map[string]int `json:"stock"`
	BuyPrice  *int           `json:"buy_price"`
	SellPrice *int           `json:"sell_price"`
}

// handleCreatePlayShop lets the campaign dm create a new shop within a
// settlement. Only the dm may call this; unknown campaigns or settlements
// return 404, invalid payloads return 400, and duplicate shop ids within the
// settlement return 409.
func handleCreatePlayShop(w http.ResponseWriter, r *http.Request, campaignID, settlementID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req playShopRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ShopID == "" || req.Name == "" {
		writeError(w, http.StatusBadRequest, "shop_id and name are required")
		return
	}
	if len(req.Stock) == 0 {
		writeError(w, http.StatusBadRequest, "stock must be a nonempty object of valid item ids to positive quantities")
		return
	}
	for itemID, qty := range req.Stock {
		if !validInventoryItems[itemID] || qty <= 0 {
			writeError(w, http.StatusBadRequest, "stock must be a nonempty object of valid item ids to positive quantities")
			return
		}
	}
	if req.BuyPrice == nil || *req.BuyPrice <= 0 {
		writeError(w, http.StatusBadRequest, "buy_price must be a positive integer")
		return
	}
	if req.SellPrice == nil || *req.SellPrice < 0 {
		writeError(w, http.StatusBadRequest, "sell_price must be a nonnegative integer")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may create shops")
		return
	}
	s := c.Settlements[settlementID]
	if s == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "settlement not found")
		return
	}
	if s.Shops == nil {
		s.Shops = make(map[string]*playShop)
	}
	if _, exists := s.Shops[req.ShopID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "shop_id already exists in this settlement")
		return
	}

	stock := make(map[string]int, len(req.Stock))
	for itemID, qty := range req.Stock {
		stock[itemID] = qty
	}
	shop := &playShop{
		ShopID:    req.ShopID,
		Name:      req.Name,
		Stock:     stock,
		BuyPrice:  *req.BuyPrice,
		SellPrice: *req.SellPrice,
	}
	s.Shops[req.ShopID] = shop
	resp := playShopResponse(shop)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

// handleGetPlayShop returns a single shop. The dm may always read shops. A
// player may read a shop only after that player's character has discovered
// the containing settlement; undiscovered shops return 404 to players.
func handleGetPlayShop(w http.ResponseWriter, r *http.Request, campaignID, settlementID, shopID string) {
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
		writeError(w, http.StatusForbidden, "only the owner or a member may view shops")
		return
	}
	s := c.Settlements[settlementID]
	if s == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "settlement not found")
		return
	}
	shop := s.Shops[shopID]
	if shop == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "shop not found")
		return
	}

	if c.Owner != username {
		var member *playMember
		for _, m := range c.Members {
			if m.Username == username {
				member = m
				break
			}
		}
		if member == nil {
			playMu.Unlock()
			writeError(w, http.StatusForbidden, "only campaign members may view shops")
			return
		}
		discovered := false
		for _, charID := range s.DiscoveredBy {
			if charID == member.CharacterID {
				discovered = true
				break
			}
		}
		if !discovered {
			playMu.Unlock()
			writeError(w, http.StatusNotFound, "shop not found")
			return
		}
	}

	resp := playShopResponse(shop)
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

type playShopTradeRequest struct {
	CharacterID string `json:"character_id"`
	ItemID      string `json:"item_id"`
	Quantity    *int   `json:"quantity"`
}

// handlePlayShopBuy lets a character's owning player purchase items from a
// shop, atomically decrementing shop stock, subtracting gold, and adding the
// items to the character's inventory. Insufficient stock or funds return 409
// and must not partially mutate state.
func handlePlayShopBuy(w http.ResponseWriter, r *http.Request, campaignID, settlementID, shopID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req playShopTradeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CharacterID == "" || !validInventoryItems[req.ItemID] || req.Quantity == nil || *req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "character_id and a valid item_id are required and quantity must be positive")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	s := c.Settlements[settlementID]
	if s == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "settlement not found")
		return
	}
	shop := s.Shops[shopID]
	if shop == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "shop not found")
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
		writeError(w, http.StatusForbidden, "the dm may not buy from a shop")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may buy from a shop")
		return
	}

	qty := *req.Quantity
	cost := shop.BuyPrice * qty
	if shop.Stock[req.ItemID] < qty || member.Gold < cost {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "insufficient stock or funds")
		return
	}

	shop.Stock[req.ItemID] -= qty
	member.Gold -= cost
	if member.Items == nil {
		member.Items = make(map[string]int)
	}
	member.Items[req.ItemID] += qty

	resp := map[string]interface{}{
		"character_id": req.CharacterID,
		"item_id":      req.ItemID,
		"quantity":     qty,
		"gold":         member.Gold,
		"stock":        shop.Stock[req.ItemID],
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

// handlePlayShopSell lets a character's owning player sell items to a shop,
// atomically removing items from the character's inventory, adding gold, and
// incrementing shop stock. Insufficient inventory returns 409 and must not
// partially mutate state.
func handlePlayShopSell(w http.ResponseWriter, r *http.Request, campaignID, settlementID, shopID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req playShopTradeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CharacterID == "" || !validInventoryItems[req.ItemID] || req.Quantity == nil || *req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "character_id and a valid item_id are required and quantity must be positive")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	s := c.Settlements[settlementID]
	if s == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "settlement not found")
		return
	}
	shop := s.Shops[shopID]
	if shop == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "shop not found")
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
		writeError(w, http.StatusForbidden, "the dm may not sell to a shop")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may sell to a shop")
		return
	}

	qty := *req.Quantity
	if member.Items[req.ItemID] < qty {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "insufficient inventory")
		return
	}

	member.Items[req.ItemID] -= qty
	member.Gold += shop.SellPrice * qty
	if shop.Stock == nil {
		shop.Stock = make(map[string]int)
	}
	shop.Stock[req.ItemID] += qty

	resp := map[string]interface{}{
		"character_id": req.CharacterID,
		"item_id":      req.ItemID,
		"quantity":     qty,
		"gold":         member.Gold,
		"stock":        shop.Stock[req.ItemID],
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}
