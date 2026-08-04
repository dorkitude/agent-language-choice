package main

import (
	"net/http"
	"sync"
)

// playShop is a DM-created settlement shop with deterministic stock and
// prices, backed by campaign inventory and currency for player trades.
type playShop struct {
	CampaignID   string
	SettlementID string
	ShopID       string
	Name         string
	Stock        map[string]int
	BuyPrice     int
	SellPrice    int
}

// campaignShopsMu guards campaignShops, the in-memory index mirroring the
// play_shops table. Keyed by campaign id, then settlement id, holding shops
// in creation order.
var (
	campaignShopsMu sync.Mutex
	campaignShops   = map[string]map[string][]*playShop{}
)

// findShop returns the shop with the given id within settlementID in
// campaignID, or nil. Callers must already hold campaignShopsMu.
func findShop(campaignID, settlementID, shopID string) *playShop {
	for _, s := range campaignShops[campaignID][settlementID] {
		if s.ShopID == shopID {
			return s
		}
	}
	return nil
}

// shopJSON renders s as its exact API shape.
func shopJSON(s *playShop) map[string]any {
	return map[string]any{
		"shop_id":    s.ShopID,
		"name":       s.Name,
		"stock":      s.Stock,
		"buy_price":  s.BuyPrice,
		"sell_price": s.SellPrice,
	}
}

// validShopStock reports whether stock is a nonempty map of valid catalog
// item ids to positive integer quantities.
func validShopStock(stock map[string]int) bool {
	if len(stock) == 0 {
		return false
	}
	for itemID, qty := range stock {
		if !inventoryCatalog[itemID] {
			return false
		}
		if qty <= 0 {
			return false
		}
	}
	return true
}

type shopRequest struct {
	ShopID    string         `json:"shop_id"`
	Name      string         `json:"name"`
	Stock     map[string]int `json:"stock"`
	BuyPrice  int            `json:"buy_price"`
	SellPrice int            `json:"sell_price"`
}

// createShopHandler lets the campaign's owning dm create a new shop within a
// settlement.
func createShopHandler(w http.ResponseWriter, r *http.Request, campaignID, settlementID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req shopRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may create shops")
		return
	}

	campaignSettlementsMu.Lock()
	defer campaignSettlementsMu.Unlock()

	if findSettlement(campaignID, settlementID) == nil {
		writeError(w, http.StatusNotFound, "unknown settlement id")
		return
	}

	if req.ShopID == "" || req.Name == "" || req.BuyPrice <= 0 || req.SellPrice < 0 || !validShopStock(req.Stock) {
		writeError(w, http.StatusBadRequest, "shop_id and name are required nonempty strings, stock must be a nonempty map of valid item ids to positive quantities, buy_price must be positive, and sell_price must be nonnegative")
		return
	}

	campaignShopsMu.Lock()
	defer campaignShopsMu.Unlock()

	if findShop(campaignID, settlementID, req.ShopID) != nil {
		writeError(w, http.StatusConflict, "shop_id already exists in this settlement")
		return
	}

	stock := make(map[string]int, len(req.Stock))
	for itemID, qty := range req.Stock {
		stock[itemID] = qty
	}

	s := &playShop{
		CampaignID:   campaignID,
		SettlementID: settlementID,
		ShopID:       req.ShopID,
		Name:         req.Name,
		Stock:        stock,
		BuyPrice:     req.BuyPrice,
		SellPrice:    req.SellPrice,
	}
	if err := saveShopToDB(s); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save shop")
		return
	}
	if campaignShops[campaignID] == nil {
		campaignShops[campaignID] = map[string][]*playShop{}
	}
	campaignShops[campaignID][settlementID] = append(campaignShops[campaignID][settlementID], s)

	writeJSON(w, http.StatusCreated, shopJSON(s))
}

// getShopHandler returns a shop. The dm may always read a shop; a player may
// read one only after that player's character has discovered the containing
// settlement.
func getShopHandler(w http.ResponseWriter, r *http.Request, campaignID, settlementID, shopID string) {
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
	isDM := actor.Username == c.Owner
	if !isDM && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be the dm or a member of this campaign")
		return
	}

	campaignSettlementsMu.Lock()
	defer campaignSettlementsMu.Unlock()

	s := findSettlement(campaignID, settlementID)
	if s == nil {
		writeError(w, http.StatusNotFound, "unknown settlement id")
		return
	}

	if !isDM {
		playMembersMu.Lock()
		member, exists := playMembers[campaignID][actor.Username]
		playMembersMu.Unlock()
		if !exists || member.CharacterID == "" {
			writeError(w, http.StatusNotFound, "unknown shop id")
			return
		}
		discovered := false
		for _, cid := range s.DiscoveredBy {
			if cid == member.CharacterID {
				discovered = true
				break
			}
		}
		if !discovered {
			writeError(w, http.StatusNotFound, "unknown shop id")
			return
		}
	}

	campaignShopsMu.Lock()
	defer campaignShopsMu.Unlock()

	shop := findShop(campaignID, settlementID, shopID)
	if shop == nil {
		writeError(w, http.StatusNotFound, "unknown shop id")
		return
	}

	writeJSON(w, http.StatusOK, shopJSON(shop))
}

type shopTradeRequest struct {
	CharacterID string `json:"character_id"`
	ItemID      string `json:"item_id"`
	Quantity    int    `json:"quantity"`
}

// buyShopHandler lets a character's owner purchase items from a shop,
// atomically debiting gold, decrementing shop stock, and crediting the
// character's inventory.
func buyShopHandler(w http.ResponseWriter, r *http.Request, campaignID, settlementID, shopID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req shopTradeRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	campaignSettlementsMu.Lock()
	defer campaignSettlementsMu.Unlock()

	if findSettlement(campaignID, settlementID) == nil {
		writeError(w, http.StatusNotFound, "unknown settlement id")
		return
	}

	campaignShopsMu.Lock()
	defer campaignShopsMu.Unlock()

	shop := findShop(campaignID, settlementID, shopID)
	if shop == nil {
		writeError(w, http.StatusNotFound, "unknown shop id")
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
		writeError(w, http.StatusForbidden, "the dm may not buy from shops")
		return
	}
	if actor.Username != playMemberOwner(member) {
		writeError(w, http.StatusForbidden, "only the character's owner may buy")
		return
	}

	if !inventoryCatalog[req.ItemID] || req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "item_id must be a valid inventory item and quantity must be positive")
		return
	}

	if shop.Stock[req.ItemID] < req.Quantity {
		writeError(w, http.StatusConflict, "insufficient shop stock")
		return
	}

	currencyMu.Lock()
	defer currencyMu.Unlock()

	cur, err := getOrInitCurrency(campaignID, req.CharacterID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to load currency")
		return
	}

	cost := shop.BuyPrice * req.Quantity
	if cur.Gold < cost {
		writeError(w, http.StatusConflict, "insufficient gold")
		return
	}

	inventoryItemsMu.Lock()
	defer inventoryItemsMu.Unlock()

	cur.Gold -= cost
	if err := saveCurrencyToDB(cur); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save currency")
		return
	}

	shop.Stock[req.ItemID] -= req.Quantity
	if err := saveShopToDB(shop); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save shop")
		return
	}

	if inventoryItems[campaignID] == nil {
		inventoryItems[campaignID] = map[string]map[string]*playInventoryItem{}
	}
	if inventoryItems[campaignID][req.CharacterID] == nil {
		inventoryItems[campaignID][req.CharacterID] = map[string]*playInventoryItem{}
	}
	item, exists := inventoryItems[campaignID][req.CharacterID][req.ItemID]
	if !exists {
		item = &playInventoryItem{CampaignID: campaignID, CharacterID: req.CharacterID, ItemID: req.ItemID, Quantity: 0}
		inventoryItems[campaignID][req.CharacterID][req.ItemID] = item
	}
	item.Quantity += req.Quantity
	if err := saveInventoryItemToDB(item); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save inventory item")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"character_id": req.CharacterID,
		"item_id":      req.ItemID,
		"quantity":     req.Quantity,
		"gold":         cur.Gold,
		"stock":        shop.Stock[req.ItemID],
	})
}

// sellShopHandler lets a character's owner sell items to a shop, atomically
// removing inventory, crediting gold, and incrementing shop stock.
func sellShopHandler(w http.ResponseWriter, r *http.Request, campaignID, settlementID, shopID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req shopTradeRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	campaignSettlementsMu.Lock()
	defer campaignSettlementsMu.Unlock()

	if findSettlement(campaignID, settlementID) == nil {
		writeError(w, http.StatusNotFound, "unknown settlement id")
		return
	}

	campaignShopsMu.Lock()
	defer campaignShopsMu.Unlock()

	shop := findShop(campaignID, settlementID, shopID)
	if shop == nil {
		writeError(w, http.StatusNotFound, "unknown shop id")
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
		writeError(w, http.StatusForbidden, "the dm may not sell to shops")
		return
	}
	if actor.Username != playMemberOwner(member) {
		writeError(w, http.StatusForbidden, "only the character's owner may sell")
		return
	}

	if !inventoryCatalog[req.ItemID] || req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "item_id must be a valid inventory item and quantity must be positive")
		return
	}

	inventoryItemsMu.Lock()
	defer inventoryItemsMu.Unlock()

	var item *playInventoryItem
	if inventoryItems[campaignID] != nil {
		item = inventoryItems[campaignID][req.CharacterID][req.ItemID]
	}
	held := 0
	if item != nil {
		held = item.Quantity
	}
	if req.Quantity > held {
		writeError(w, http.StatusConflict, "insufficient inventory")
		return
	}

	currencyMu.Lock()
	defer currencyMu.Unlock()

	cur, err := getOrInitCurrency(campaignID, req.CharacterID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to load currency")
		return
	}

	item.Quantity -= req.Quantity
	if item.Quantity <= 0 {
		if err := deleteInventoryItemFromDB(campaignID, req.CharacterID, req.ItemID); err != nil {
			writeError(w, http.StatusInternalServerError, "failed to remove inventory item")
			return
		}
		delete(inventoryItems[campaignID][req.CharacterID], req.ItemID)
	} else {
		if err := saveInventoryItemToDB(item); err != nil {
			writeError(w, http.StatusInternalServerError, "failed to save inventory item")
			return
		}
	}

	cur.Gold += shop.SellPrice * req.Quantity
	if err := saveCurrencyToDB(cur); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save currency")
		return
	}

	shop.Stock[req.ItemID] += req.Quantity
	if err := saveShopToDB(shop); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save shop")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"character_id": req.CharacterID,
		"item_id":      req.ItemID,
		"quantity":     req.Quantity,
		"gold":         cur.Gold,
		"stock":        shop.Stock[req.ItemID],
	})
}
