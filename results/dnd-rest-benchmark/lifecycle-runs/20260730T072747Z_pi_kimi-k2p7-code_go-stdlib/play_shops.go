package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// shopResponse is the exact shape returned for a shop.
type shopResponse struct {
	ShopID    string         `json:"shop_id"`
	Name      string         `json:"name"`
	Stock     map[string]int `json:"stock"`
	BuyPrice  int            `json:"buy_price"`
	SellPrice int            `json:"sell_price"`
}

// shopCreateRequest binds the payload for creating a shop.
type shopCreateRequest struct {
	ShopID    string         `json:"shop_id"`
	Name      string         `json:"name"`
	Stock     map[string]int `json:"stock"`
	BuyPrice  int            `json:"buy_price"`
	SellPrice int            `json:"sell_price"`
}

// tradeRequest binds the payload for buy/sell operations.
type tradeRequest struct {
	CharacterID string `json:"character_id"`
	ItemID      string `json:"item_id"`
	Quantity    int    `json:"quantity"`
}

// tradeResponse is the shape returned after a successful buy or sell.
type tradeResponse struct {
	CharacterID string `json:"character_id"`
	ItemID      string `json:"item_id"`
	Quantity    int    `json:"quantity"`
	Gold        int    `json:"gold"`
	Stock       int    `json:"stock"`
}

// validateShopRequest checks the shop creation payload. It returns a non-empty
// error message if any constraint fails.
func validateShopRequest(req *shopCreateRequest) string {
	if req.ShopID == "" || req.Name == "" {
		return "invalid shop"
	}
	if len(req.Stock) == 0 {
		return "invalid shop"
	}
	for itemID, qty := range req.Stock {
		if !validInventoryItemIDs[itemID] || qty <= 0 {
			return "invalid shop"
		}
	}
	if req.BuyPrice <= 0 {
		return "invalid shop"
	}
	if req.SellPrice < 0 {
		return "invalid shop"
	}
	return ""
}

// queryShop loads a shop by campaign, settlement, and shop id. The caller must
// hold dbMu.
func queryShop(campaignID, settlementID, shopID string) (*shopResponse, bool, error) {
	var rows []struct {
		ShopID    string `json:"shop_id"`
		Name      string `json:"name"`
		Stock     string `json:"stock"`
		BuyPrice  int    `json:"buy_price"`
		SellPrice int    `json:"sell_price"`
	}
	sql := fmt.Sprintf("SELECT shop_id, name, stock, buy_price, sell_price FROM campaign_shops WHERE campaign_id=%s AND settlement_id=%s AND shop_id=%s LIMIT 1;", sq(campaignID), sq(settlementID), sq(shopID))
	if err := queryRows(sql, &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	var stock map[string]int
	if err := json.Unmarshal([]byte(rows[0].Stock), &stock); err != nil {
		return nil, false, err
	}
	return &shopResponse{
		ShopID:    rows[0].ShopID,
		Name:      rows[0].Name,
		Stock:     stock,
		BuyPrice:  rows[0].BuyPrice,
		SellPrice: rows[0].SellPrice,
	}, true, nil
}

// queryShopExists reports whether a shop with the given id exists in a
// settlement. The caller must hold dbMu.
func queryShopExists(campaignID, settlementID, shopID string) (bool, error) {
	return queryExists(fmt.Sprintf("SELECT 1 FROM campaign_shops WHERE campaign_id=%s AND settlement_id=%s AND shop_id=%s LIMIT 1;", sq(campaignID), sq(settlementID), sq(shopID)))
}

// createShopHandler creates a new shop in a settlement. Only the campaign DM
// may create shops.
func createShopHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requireDM(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")
	settlementID := r.PathValue("settlement_id")

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("shop create campaign query error: %v", err)
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

	_, ok, err = querySettlement(campaignID, settlementID)
	if err != nil {
		log.Printf("shop create settlement query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "settlement not found")
		return
	}

	var req shopCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if msg := validateShopRequest(&req); msg != "" {
		writeError(w, http.StatusBadRequest, msg)
		return
	}

	dup, err := queryShopExists(campaignID, settlementID, req.ShopID)
	if err != nil {
		log.Printf("shop duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dup {
		writeError(w, http.StatusConflict, "shop already exists")
		return
	}

	stockJSON, err := json.Marshal(req.Stock)
	if err != nil {
		log.Printf("shop stock marshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	insertSQL := fmt.Sprintf("INSERT INTO campaign_shops (campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price) VALUES (%s, %s, %s, %s, %s, %d, %d);",
		sq(campaignID), sq(settlementID), sq(req.ShopID), sq(req.Name), sq(string(stockJSON)), req.BuyPrice, req.SellPrice)
	if err := dbExec(insertSQL); err != nil {
		log.Printf("shop insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, shopResponse{
		ShopID:    req.ShopID,
		Name:      req.Name,
		Stock:     req.Stock,
		BuyPrice:  req.BuyPrice,
		SellPrice: req.SellPrice,
	})
}

// getShopHandler reads a shop. The DM may always read; players may read only
// shops in settlements discovered by their character.
func getShopHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	settlementID := r.PathValue("settlement_id")
	shopID := r.PathValue("shop_id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("shop get campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	settlement, ok, err := querySettlement(campaignID, settlementID)
	if err != nil {
		log.Printf("shop get settlement query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "settlement not found")
		return
	}

	shop, ok, err := queryShop(campaignID, settlementID, shopID)
	if err != nil {
		log.Printf("shop get shop query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "shop not found")
		return
	}

	if campaign.Owner != username {
		member, ok, err := queryPlayCampaignMemberByUsername(campaignID, username)
		if err != nil {
			log.Printf("shop get member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if !ok {
			writeError(w, http.StatusForbidden, "forbidden")
			return
		}
		playerDiscovered := false
		for _, id := range settlement.DiscoveredBy {
			if id == member.CharacterID {
				playerDiscovered = true
				break
			}
		}
		if !playerDiscovered {
			writeError(w, http.StatusNotFound, "shop not found")
			return
		}
	}

	writeJSON(w, http.StatusOK, shop)
}

// buyFromShopHandler lets a character buy items from a shop. Only the owning
// player may buy; the DM is rejected. The transaction is atomic and fails with
// 409 if stock or funds are insufficient.
func buyFromShopHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requirePlayer(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")
	settlementID := r.PathValue("settlement_id")
	shopID := r.PathValue("shop_id")

	_, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("shop buy campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	_, ok, err = querySettlement(campaignID, settlementID)
	if err != nil {
		log.Printf("shop buy settlement query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "settlement not found")
		return
	}

	shop, ok, err := queryShop(campaignID, settlementID, shopID)
	if err != nil {
		log.Printf("shop buy shop query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "shop not found")
		return
	}

	var req tradeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CharacterID == "" {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if !validInventoryItemIDs[req.ItemID] || req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "invalid item or quantity")
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, req.CharacterID)
	if err != nil {
		log.Printf("shop buy member query error: %v", err)
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

	stockQty, ok := shop.Stock[req.ItemID]
	if !ok || stockQty < req.Quantity {
		writeError(w, http.StatusConflict, "insufficient stock")
		return
	}
	cost := shop.BuyPrice * req.Quantity
	if member.Gold < cost {
		writeError(w, http.StatusConflict, "insufficient gold")
		return
	}

	newStockQty := stockQty - req.Quantity
	newGold := member.Gold - cost
	shop.Stock[req.ItemID] = newStockQty

	stockJSON, err := json.Marshal(shop.Stock)
	if err != nil {
		log.Printf("shop buy stock marshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	txSQL := fmt.Sprintf("BEGIN; UPDATE campaign_shops SET stock=%s WHERE campaign_id=%s AND settlement_id=%s AND shop_id=%s; UPDATE play_campaign_members SET gold=%d WHERE campaign_id=%s AND character_id=%s; INSERT INTO character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (%s, %s, %s, %d) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity; COMMIT;",
		sq(string(stockJSON)), sq(campaignID), sq(settlementID), sq(shopID),
		newGold, sq(campaignID), sq(req.CharacterID),
		sq(campaignID), sq(req.CharacterID), sq(req.ItemID), req.Quantity)
	if err := dbExec(txSQL); err != nil {
		log.Printf("shop buy transaction error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, tradeResponse{
		CharacterID: req.CharacterID,
		ItemID:      req.ItemID,
		Quantity:    req.Quantity,
		Gold:        newGold,
		Stock:       newStockQty,
	})
}

// sellToShopHandler lets a character sell items to a shop. Only the owning
// player may sell; the DM is rejected. The transaction is atomic and fails
// with 409 if the character lacks sufficient inventory.
func sellToShopHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requirePlayer(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")
	settlementID := r.PathValue("settlement_id")
	shopID := r.PathValue("shop_id")

	_, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("shop sell campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	_, ok, err = querySettlement(campaignID, settlementID)
	if err != nil {
		log.Printf("shop sell settlement query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "settlement not found")
		return
	}

	shop, ok, err := queryShop(campaignID, settlementID, shopID)
	if err != nil {
		log.Printf("shop sell shop query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "shop not found")
		return
	}

	var req tradeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CharacterID == "" {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if !validInventoryItemIDs[req.ItemID] || req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "invalid item or quantity")
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, req.CharacterID)
	if err != nil {
		log.Printf("shop sell member query error: %v", err)
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

	held, err := queryCharacterInventoryItemQuantity(campaignID, req.CharacterID, req.ItemID)
	if err != nil {
		log.Printf("shop sell held query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if held < req.Quantity {
		writeError(w, http.StatusConflict, "insufficient inventory")
		return
	}

	newStockQty := shop.Stock[req.ItemID] + req.Quantity
	newGold := member.Gold + shop.SellPrice*req.Quantity
	shop.Stock[req.ItemID] = newStockQty

	stockJSON, err := json.Marshal(shop.Stock)
	if err != nil {
		log.Printf("shop sell stock marshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	var inventorySQL string
	remaining := held - req.Quantity
	if remaining == 0 {
		inventorySQL = fmt.Sprintf("DELETE FROM character_inventory_items WHERE campaign_id=%s AND character_id=%s AND item_id=%s;", sq(campaignID), sq(req.CharacterID), sq(req.ItemID))
	} else {
		inventorySQL = fmt.Sprintf("UPDATE character_inventory_items SET quantity=%d WHERE campaign_id=%s AND character_id=%s AND item_id=%s;", remaining, sq(campaignID), sq(req.CharacterID), sq(req.ItemID))
	}

	txSQL := fmt.Sprintf("BEGIN; UPDATE campaign_shops SET stock=%s WHERE campaign_id=%s AND settlement_id=%s AND shop_id=%s; UPDATE play_campaign_members SET gold=%d WHERE campaign_id=%s AND character_id=%s; %s COMMIT;",
		sq(string(stockJSON)), sq(campaignID), sq(settlementID), sq(shopID),
		newGold, sq(campaignID), sq(req.CharacterID),
		inventorySQL)
	if err := dbExec(txSQL); err != nil {
		log.Printf("shop sell transaction error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, tradeResponse{
		CharacterID: req.CharacterID,
		ItemID:      req.ItemID,
		Quantity:    req.Quantity,
		Gold:        newGold,
		Stock:       newStockQty,
	})
}
