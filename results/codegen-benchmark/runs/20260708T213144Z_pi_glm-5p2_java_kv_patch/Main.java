import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

public class Main {

    /** A single parsed input record. */
    static final class Record {
        long ts;
        int order;   // original input index, for tie-breaking stability
        String op;
        String key;
        String value;
    }

    public static void main(String[] args) throws IOException {
        // Read all of stdin.
        BufferedReader reader = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        List<Record> records = new ArrayList<>();
        String line;
        int idx = 0;
        while ((line = reader.readLine()) != null) {
            if (line.isEmpty()) continue;
            records.add(parseLine(line, idx++));
        }

        // Stable sort by ts ascending. Java's List.sort is stable, so ties keep
        // input order automatically. We include `order` for explicitness.
        records.sort((a, b) -> {
            int c = Long.compare(a.ts, b.ts);
            if (c != 0) return c;
            return Integer.compare(a.order, b.order);
        });

        // Apply operations. TreeMap keyed by UTF-8 bytewise order.
        TreeMap<String, String> map = new TreeMap<>(Main::compareBytes);
        for (Record r : records) {
            if ("set".equals(r.op)) {
                map.put(r.key, r.value);
            } else if ("delete".equals(r.op)) {
                map.remove(r.key);
            }
        }

        // Emit final map, sorted by key (TreeMap already is).
        StringBuilder out = new StringBuilder();
        for (Map.Entry<String, String> e : map.entrySet()) {
            out.append(e.getKey()).append('=').append(e.getValue()).append('\n');
        }
        PrintStream ps = new PrintStream(new FileOutputStream(FileDescriptor.out), true, StandardCharsets.UTF_8);
        ps.print(out);
        ps.flush();
    }

    /** Compare two strings by their UTF-8 byte sequences (bytewise / code-point order). */
    private static int compareBytes(String a, String b) {
        byte[] xa = a.getBytes(StandardCharsets.UTF_8);
        byte[] xb = b.getBytes(StandardCharsets.UTF_8);
        int len = Math.min(xa.length, xb.length);
        for (int i = 0; i < len; i++) {
            int d = (xa[i] & 0xff) - (xb[i] & 0xff);
            if (d != 0) return d;
        }
        return xa.length - xb.length;
    }

    // ---- minimal JSON parser (stdlib only) ----

    private static Record parseLine(String s, int order) {
        JsonParser p = new JsonParser(s);
        Object o = p.parseValue();
        if (!(o instanceof Map)) throw new RuntimeException("expected JSON object");
        @SuppressWarnings("unchecked")
        Map<String, Object> obj = (Map<String, Object>) o;
        Record r = new Record();
        r.order = order;
        r.ts = toLong(obj.get("ts"));
        r.op = toString(obj.get("op"));
        r.key = toString(obj.get("key"));
        r.value = toString(obj.get("value"));
        return r;
    }

    private static long toLong(Object o) {
        if (o == null) return 0L;
        if (o instanceof Long) return (Long) o;
        if (o instanceof Double) return ((Double) o).longValue();
        return Long.parseLong(o.toString());
    }

    private static String toString(Object o) {
        return o == null ? "" : o.toString();
    }

    /** Tiny recursive-descent JSON parser. */
    static final class JsonParser {
        private final String s;
        private int pos;

        JsonParser(String s) { this.s = s; }

        Object parseValue() {
            skipWs();
            char c = s.charAt(pos);
            switch (c) {
                case '{': return parseObject();
                case '[': return parseArray();
                case '"': return parseString();
                case 't': pos += 4; return Boolean.TRUE;
                case 'f': pos += 5; return Boolean.FALSE;
                case 'n': pos += 4; return null;
                default: return parseNumber();
            }
        }

        private void skipWs() {
            while (pos < s.length() && Character.isWhitespace(s.charAt(pos))) pos++;
        }

        private Map<String, Object> parseObject() {
            Map<String, Object> map = new LinkedHashMap<>();
            pos++; // consume '{'
            skipWs();
            if (pos < s.length() && s.charAt(pos) == '}') { pos++; return map; }
            while (true) {
                skipWs();
                String key = parseString();
                skipWs();
                if (s.charAt(pos) != ':') throw new RuntimeException("expected ':' at " + pos);
                pos++; // consume ':'
                Object val = parseValue();
                map.put(key, val);
                skipWs();
                char c = s.charAt(pos);
                if (c == ',') { pos++; continue; }
                if (c == '}') { pos++; break; }
                throw new RuntimeException("expected ',' or '}' at " + pos);
            }
            return map;
        }

        private List<Object> parseArray() {
            List<Object> list = new ArrayList<>();
            pos++; // consume '['
            skipWs();
            if (pos < s.length() && s.charAt(pos) == ']') { pos++; return list; }
            while (true) {
                list.add(parseValue());
                skipWs();
                char c = s.charAt(pos);
                if (c == ',') { pos++; continue; }
                if (c == ']') { pos++; break; }
                throw new RuntimeException("expected ',' or ']' at " + pos);
            }
            return list;
        }

        private String parseString() {
            skipWs();
            if (s.charAt(pos) != '"') throw new RuntimeException("expected string at " + pos);
            pos++; // opening quote
            StringBuilder sb = new StringBuilder();
            while (pos < s.length()) {
                char c = s.charAt(pos++);
                if (c == '"') return sb.toString();
                if (c == '\\') {
                    char e = s.charAt(pos++);
                    switch (e) {
                        case '"':  sb.append('"');  break;
                        case '\\': sb.append('\\'); break;
                        case '/':  sb.append('/');  break;
                        case 'b':  sb.append('\b'); break;
                        case 'f':  sb.append('\f'); break;
                        case 'n':  sb.append('\n'); break;
                        case 'r':  sb.append('\r'); break;
                        case 't':  sb.append('\t'); break;
                        case 'u':
                            String hex = s.substring(pos, pos + 4);
                            sb.append((char) Integer.parseInt(hex, 16));
                            pos += 4;
                            break;
                        default: throw new RuntimeException("bad escape \\" + e);
                    }
                } else {
                    sb.append(c);
                }
            }
            throw new RuntimeException("unterminated string");
        }

        private Object parseNumber() {
            int start = pos;
            while (pos < s.length() && "+-0123456789.eE".indexOf(s.charAt(pos)) >= 0) pos++;
            String num = s.substring(start, pos);
            if (num.indexOf('.') >= 0 || num.indexOf('e') >= 0 || num.indexOf('E') >= 0) {
                return Double.parseDouble(num);
            }
            return Long.parseLong(num);
        }
    }
}
