package dnd.json;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Minimal recursive-descent JSON parser.
 * Supports objects, arrays, strings, numbers, booleans, and null.
 */
class JsonParser {
    private final String s;
    private int pos;

    JsonParser(String s) {
        this.s = s;
        this.pos = 0;
    }

    Object parse() {
        skipWhitespace();
        return parseValue();
    }

    private Object parseValue() {
        skipWhitespace();
        char c = s.charAt(pos);
        if (c == '{') return parseObject();
        if (c == '[') return parseArray();
        if (c == '"') return parseString();
        if (c == '-' || (c >= '0' && c <= '9')) return parseNumber();
        if (c == 't' || c == 'f') return parseBoolean();
        if (c == 'n') {
            expect("null");
            return null;
        }
        throw new RuntimeException("Unexpected char: " + c);
    }

    private Map<String, Object> parseObject() {
        Map<String, Object> map = new LinkedHashMap<>();
        expect('{');
        skipWhitespace();
        if (peek() == '}') {
            pos++;
            return map;
        }
        while (true) {
            skipWhitespace();
            String key = parseString();
            skipWhitespace();
            expect(':');
            skipWhitespace();
            map.put(key, parseValue());
            skipWhitespace();
            char c = peek();
            if (c == ',') {
                pos++;
                continue;
            }
            if (c == '}') {
                pos++;
                break;
            }
            throw new RuntimeException("Expected , or }");
        }
        return map;
    }

    private List<Object> parseArray() {
        List<Object> list = new ArrayList<>();
        expect('[');
        skipWhitespace();
        if (peek() == ']') {
            pos++;
            return list;
        }
        while (true) {
            skipWhitespace();
            list.add(parseValue());
            skipWhitespace();
            char c = peek();
            if (c == ',') {
                pos++;
                continue;
            }
            if (c == ']') {
                pos++;
                break;
            }
            throw new RuntimeException("Expected , or ]");
        }
        return list;
    }

    private String parseString() {
        expect('"');
        StringBuilder sb = new StringBuilder();
        while (pos < s.length()) {
            char c = s.charAt(pos++);
            if (c == '"') break;
            if (c == '\\') {
                if (pos >= s.length()) throw new RuntimeException("Invalid escape");
                char esc = s.charAt(pos++);
                switch (esc) {
                    case 'n': sb.append('\n'); break;
                    case 't': sb.append('\t'); break;
                    case 'r': sb.append('\r'); break;
                    case '"': case '\\': case '/': sb.append(esc); break;
                    case 'u':
                        if (pos + 4 > s.length()) throw new RuntimeException("Invalid unicode escape");
                        String hex = s.substring(pos, pos + 4);
                        sb.append((char) Integer.parseInt(hex, 16));
                        pos += 4;
                        break;
                    default: sb.append(esc); break;
                }
            } else {
                sb.append(c);
            }
        }
        return sb.toString();
    }

    private Number parseNumber() {
        int start = pos;
        if (peek() == '-') pos++;
        while (pos < s.length() && Character.isDigit(s.charAt(pos))) pos++;
        if (pos < s.length() && s.charAt(pos) == '.') {
            pos++;
            while (pos < s.length() && Character.isDigit(s.charAt(pos))) pos++;
            return Double.parseDouble(s.substring(start, pos));
        }
        return Integer.parseInt(s.substring(start, pos));
    }

    private Boolean parseBoolean() {
        if (s.startsWith("true", pos)) {
            pos += 4;
            return true;
        }
        if (s.startsWith("false", pos)) {
            pos += 5;
            return false;
        }
        throw new RuntimeException("Expected boolean");
    }

    private void expect(char expected) {
        skipWhitespace();
        char c = peek();
        if (c != expected) throw new RuntimeException("Expected " + expected + " got " + c);
        pos++;
    }

    private void expect(String expected) {
        skipWhitespace();
        if (!s.startsWith(expected, pos)) throw new RuntimeException("Expected " + expected);
        pos += expected.length();
    }

    private char peek() {
        if (pos >= s.length()) throw new RuntimeException("Unexpected end of input");
        return s.charAt(pos);
    }

    private void skipWhitespace() {
        while (pos < s.length() && Character.isWhitespace(s.charAt(pos))) pos++;
    }
}
