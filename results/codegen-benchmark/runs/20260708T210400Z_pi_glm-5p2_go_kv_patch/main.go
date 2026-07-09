package main

import (
	"bufio"
	"encoding/json"
	"os"
	"sort"
)

type rec struct {
	ts    int64
	op    string
	key   string
	value string
}

type rawRec struct {
	TS    int64  `json:"ts"`
	Op    string `json:"op"`
	Key   string `json:"key"`
	Value string `json:"value"`
}

func main() {
	sc := bufio.NewScanner(os.Stdin)
	sc.Buffer(make([]byte, 1024*1024), 16*1024*1024)

	var recs []rec
	for sc.Scan() {
		line := sc.Bytes()
		if len(line) == 0 {
			continue
		}
		var r rawRec
		if err := json.Unmarshal(line, &r); err != nil {
			// Skip malformed lines deterministically.
			continue
		}
		recs = append(recs, rec{ts: r.TS, op: r.Op, key: r.Key, value: r.Value})
	}

	// Stable sort by ts ascending; ties preserve input order.
	sort.SliceStable(recs, func(i, j int) bool {
		return recs[i].ts < recs[j].ts
	})

	m := make(map[string]string)
	for _, r := range recs {
		switch r.op {
		case "set":
			m[r.key] = r.value
		case "delete":
			delete(m, r.key)
		}
	}

	if len(m) == 0 {
		return
	}

	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	w := bufio.NewWriter(os.Stdout)
	defer w.Flush()
	for _, k := range keys {
		w.WriteString(k)
		w.WriteByte('=')
		w.WriteString(m[k])
		w.WriteByte('\n')
	}
}
