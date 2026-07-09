package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"sort"
)

type Record struct {
	TS    int     `json:"ts"`
	Op    string  `json:"op"`
	Key   string  `json:"key"`
	Value *string `json:"value"`
	Order int
}

func main() {
	var records []Record
	in := bufio.NewReader(os.Stdin)
	order := 0
	for {
		line, err := in.ReadString('\n')
		if len(line) > 0 {
			trimmed := line
			if len(trimmed) > 0 && trimmed[len(trimmed)-1] == '\n' {
				trimmed = trimmed[:len(trimmed)-1]
			}
			if len(trimmed) > 0 && trimmed[len(trimmed)-1] == '\r' {
				trimmed = trimmed[:len(trimmed)-1]
			}
			if len(trimmed) > 0 {
				var r Record
				if err := json.Unmarshal([]byte(trimmed), &r); err != nil {
					fmt.Fprintf(os.Stderr, "json error: %v\n", err)
					os.Exit(1)
				}
				r.Order = order
				order++
				records = append(records, r)
			}
		}
		if err != nil {
			break
		}
	}

	sort.Slice(records, func(i, j int) bool {
		if records[i].TS != records[j].TS {
			return records[i].TS < records[j].TS
		}
		return records[i].Order < records[j].Order
	})

	m := make(map[string]string)
	for _, r := range records {
		switch r.Op {
		case "set":
			if r.Value != nil {
				m[r.Key] = *r.Value
			} else {
				m[r.Key] = ""
			}
		case "delete":
			delete(m, r.Key)
		}
	}

	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	out := bufio.NewWriter(os.Stdout)
	for _, k := range keys {
		fmt.Fprintf(out, "%s=%s\n", k, m[k])
	}
	out.Flush()
}
