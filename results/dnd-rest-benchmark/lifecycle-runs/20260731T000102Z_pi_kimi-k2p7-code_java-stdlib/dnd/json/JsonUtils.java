package dnd.json;

import java.util.List;
import java.util.Map;

/**
 * Lightweight JSON serializer and convenience helpers.
 * The output format must remain stable because the test suite expects
 * exact field order and number formatting.
 */
public final class JsonUtils {
    private JsonUtils() {}

    @SuppressWarnings("unchecked")
    public static Map<String, Object> parseJsonObject(String s) {
        return (Map<String, Object>) new JsonParser(s).parse();
    }

    @SuppressWarnings("unchecked")
    public static Object parseJson(String s) {
        return new JsonParser(s).parse();
    }

    public static int toInt(Object value) {
        if (value instanceof Integer) return (Integer) value;
        if (value instanceof Long) return ((Long) value).intValue();
        if (value instanceof Double) return ((Double) value).intValue();
        if (value instanceof String) return Integer.parseInt((String) value);
        throw new RuntimeException("Cannot convert to int: " + value);
    }

    public static String toJson(Object value) {
        if (value == null) return "null";
        if (value instanceof String) return jsonString((String) value);
        if (value instanceof Boolean) return value.toString();
        if (value instanceof Number) {
            double d = ((Number) value).doubleValue();
            long l = ((Number) value).longValue();
            if (d == l) return Long.toString(l);
            return Double.toString(d);
        }
        if (value instanceof List) {
            StringBuilder sb = new StringBuilder();
            sb.append('[');
            boolean first = true;
            for (Object item : (List<?>) value) {
                if (!first) sb.append(',');
                sb.append(toJson(item));
                first = false;
            }
            sb.append(']');
            return sb.toString();
        }
        if (value instanceof Map) {
            StringBuilder sb = new StringBuilder();
            sb.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> entry : ((Map<?, ?>) value).entrySet()) {
                if (!first) sb.append(',');
                sb.append(jsonString(entry.getKey().toString()));
                sb.append(':');
                sb.append(toJson(entry.getValue()));
                first = false;
            }
            sb.append('}');
            return sb.toString();
        }
        return jsonString(value.toString());
    }

    private static String jsonString(String s) {
        StringBuilder sb = new StringBuilder();
        sb.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
            }
        }
        sb.append('"');
        return sb.toString();
    }
}
