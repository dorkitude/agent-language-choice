import java.io.*;
import java.util.*;

public class Main {
  public static void main(String[] args) throws Exception {
    Map<String, Long> balances = new TreeMap<>();
    BufferedReader br = new BufferedReader(new InputStreamReader(System.in));
    String line;
    while ((line = br.readLine()) != null) {
      String[] parts = line.split(",", -1);
      if (parts.length != 2 || parts[0].isEmpty()) continue;
      try {
        long delta = Long.parseLong(parts[1]);
        balances.merge(parts[0], delta, Long::sum);
      } catch (NumberFormatException ignored) {
      }
    }
    for (Map.Entry<String, Long> e : balances.entrySet()) {
      System.out.println(e.getKey() + "," + e.getValue());
    }
  }
}
