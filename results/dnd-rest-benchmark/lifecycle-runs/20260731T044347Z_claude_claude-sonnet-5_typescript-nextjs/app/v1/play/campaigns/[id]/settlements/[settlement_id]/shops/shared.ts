import { PlayShop, VALID_INVENTORY_ITEM_IDS } from "../../../../../store.js";

export function serializeShop(shop: PlayShop) {
  return {
    shop_id: shop.shop_id,
    name: shop.name,
    stock: shop.stock,
    buy_price: shop.buy_price,
    sell_price: shop.sell_price,
  };
}

export function validateStock(stock: unknown): Record<string, number> | Response {
  if (typeof stock !== "object" || stock === null || Array.isArray(stock)) {
    return Response.json({ error: "stock must be a non-empty object" }, { status: 400 });
  }
  const entries = Object.entries(stock as Record<string, unknown>);
  if (entries.length === 0) {
    return Response.json({ error: "stock must be a non-empty object" }, { status: 400 });
  }
  const normalized: Record<string, number> = {};
  for (const [itemId, quantity] of entries) {
    if (!(VALID_INVENTORY_ITEM_IDS as readonly string[]).includes(itemId)) {
      return Response.json(
        { error: `stock item ${itemId} is not a known catalog item` },
        { status: 400 },
      );
    }
    if (typeof quantity !== "number" || !Number.isInteger(quantity) || quantity < 1) {
      return Response.json(
        { error: `stock quantity for ${itemId} must be a positive integer` },
        { status: 400 },
      );
    }
    normalized[itemId] = quantity;
  }
  return normalized;
}

export function validatePrice(
  value: unknown,
  fieldName: string,
  allowZero: boolean,
): number | Response {
  const minimum = allowZero ? 0 : 1;
  if (typeof value !== "number" || !Number.isInteger(value) || value < minimum) {
    return Response.json(
      { error: `${fieldName} must be a ${allowZero ? "nonnegative" : "positive"} integer` },
      { status: 400 },
    );
  }
  return value;
}
