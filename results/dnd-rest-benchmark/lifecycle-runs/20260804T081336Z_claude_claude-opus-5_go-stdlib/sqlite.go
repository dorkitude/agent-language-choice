package main

// Minimal SQLite 3 file-format reader/writer built on the Go standard library
// only (no third-party drivers are permitted for this target). It supports the
// subset the API needs: rowid tables with TEXT/INTEGER/NULL columns, leaf and
// one level of interior b-tree pages, and payload overflow chains. Files it
// produces are readable by the real sqlite3 tooling.

import (
	"encoding/binary"
	"errors"
	"fmt"
	"os"
)

const (
	sqlitePageSize    = 4096
	sqliteVersionNum  = 3046000
	pageTypeLeafTable = 0x0d
	pageTypeIntTable  = 0x05
)

// localPayloadSize returns how many bytes of a total-length payload stay on the
// b-tree page, the rest spilling to an overflow chain. This is the SQLite
// file-format formula (reserved space is always zero here); the writer and the
// reader must compute it identically or payloads decode as garbage.
func localPayloadSize(total, pageSize int) int {
	maxLocal := pageSize - 35
	if total <= maxLocal {
		return total
	}
	minLocal := ((pageSize-12)*32)/255 - 23
	if k := minLocal + (total-minLocal)%(pageSize-4); k <= maxLocal {
		return k
	}
	return minLocal
}

// ---------- varints ----------

func encVarint(v uint64) []byte {
	if v >= 1<<56 {
		out := make([]byte, 9)
		out[8] = byte(v)
		v >>= 8
		for i := 7; i >= 0; i-- {
			out[i] = byte(v&0x7f) | 0x80
			v >>= 7
		}
		return out
	}
	var tmp [9]byte
	n := 0
	for {
		tmp[n] = byte(v & 0x7f)
		n++
		v >>= 7
		if v == 0 {
			break
		}
	}
	out := make([]byte, n)
	for i := 0; i < n; i++ {
		out[i] = tmp[n-1-i]
		if i < n-1 {
			out[i] |= 0x80
		}
	}
	return out
}

func decVarint(b []byte) (uint64, int) {
	var v uint64
	for i := 0; i < 8; i++ {
		if i >= len(b) {
			return 0, 0
		}
		c := b[i]
		if c < 0x80 {
			return v<<7 | uint64(c), i + 1
		}
		v = v<<7 | uint64(c&0x7f)
	}
	if len(b) < 9 {
		return 0, 0
	}
	return v<<8 | uint64(b[8]), 9
}

// ---------- records ----------

// encodeRecord serializes column values. Supported values are nil, int64 and
// string, matching every column this schema declares.
func encodeRecord(vals []any) ([]byte, error) {
	var types []byte
	var body []byte
	for _, v := range vals {
		switch t := v.(type) {
		case nil:
			types = append(types, encVarint(0)...)
		case int64:
			types = append(types, encVarint(6)...)
			var buf [8]byte
			binary.BigEndian.PutUint64(buf[:], uint64(t))
			body = append(body, buf[:]...)
		case int:
			types = append(types, encVarint(6)...)
			var buf [8]byte
			binary.BigEndian.PutUint64(buf[:], uint64(int64(t)))
			body = append(body, buf[:]...)
		case string:
			types = append(types, encVarint(uint64(len(t)*2+13))...)
			body = append(body, t...)
		default:
			return nil, fmt.Errorf("unsupported column value %T", v)
		}
	}
	hdrSize := 1
	for len(encVarint(uint64(len(types)+hdrSize))) != hdrSize {
		hdrSize++
	}
	out := make([]byte, 0, hdrSize+len(types)+len(body))
	out = append(out, encVarint(uint64(len(types)+hdrSize))...)
	out = append(out, types...)
	out = append(out, body...)
	return out, nil
}

func decodeRecord(payload []byte) ([]any, error) {
	hdrLen, n := decVarint(payload)
	if n == 0 || int(hdrLen) > len(payload) {
		return nil, errors.New("corrupt record header")
	}
	var serials []uint64
	for off := n; off < int(hdrLen); {
		s, m := decVarint(payload[off:])
		if m == 0 {
			return nil, errors.New("corrupt serial type")
		}
		serials = append(serials, s)
		off += m
	}
	body := payload[hdrLen:]
	vals := make([]any, 0, len(serials))
	for _, s := range serials {
		switch {
		case s == 0:
			vals = append(vals, nil)
		case s >= 1 && s <= 6:
			size := int(s)
			if s == 5 {
				size = 6
			} else if s == 6 {
				size = 8
			}
			if len(body) < size {
				return nil, errors.New("truncated integer column")
			}
			var v int64
			for i := 0; i < size; i++ {
				v = v<<8 | int64(body[i])
			}
			// sign-extend
			shift := uint(64 - 8*size)
			v = v << shift >> shift
			vals = append(vals, v)
			body = body[size:]
		case s == 8:
			vals = append(vals, int64(0))
		case s == 9:
			vals = append(vals, int64(1))
		case s >= 12 && s%2 == 0: // BLOB
			size := int((s - 12) / 2)
			if len(body) < size {
				return nil, errors.New("truncated blob column")
			}
			vals = append(vals, string(body[:size]))
			body = body[size:]
		case s >= 13 && s%2 == 1: // TEXT
			size := int((s - 13) / 2)
			if len(body) < size {
				return nil, errors.New("truncated text column")
			}
			vals = append(vals, string(body[:size]))
			body = body[size:]
		default:
			return nil, fmt.Errorf("unsupported serial type %d", s)
		}
	}
	return vals, nil
}

// ---------- writer ----------

type sqliteWriter struct {
	pages [][]byte
}

func (w *sqliteWriter) newPage() int {
	w.pages = append(w.pages, make([]byte, sqlitePageSize))
	return len(w.pages)
}

func (w *sqliteWriter) page(n int) []byte { return w.pages[n-1] }

type btreeCell struct {
	rowid int64
	data  []byte
}

// makeCell builds a table-leaf cell, spilling into overflow pages when the
// payload exceeds what a single page can hold.
func (w *sqliteWriter) makeCell(rowid int64, payload []byte) btreeCell {
	local := localPayloadSize(len(payload), sqlitePageSize)
	cell := append([]byte{}, encVarint(uint64(len(payload)))...)
	cell = append(cell, encVarint(uint64(rowid))...)
	cell = append(cell, payload[:local]...)
	if local < len(payload) {
		rest := payload[local:]
		first, prev := 0, 0
		for len(rest) > 0 {
			pg := w.newPage()
			if first == 0 {
				first = pg
			} else {
				binary.BigEndian.PutUint32(w.page(prev)[0:4], uint32(pg))
			}
			n := min(sqlitePageSize-4, len(rest))
			copy(w.page(pg)[4:], rest[:n])
			rest = rest[n:]
			prev = pg
		}
		var tail [4]byte
		binary.BigEndian.PutUint32(tail[:], uint32(first))
		cell = append(cell, tail[:]...)
	}
	return btreeCell{rowid: rowid, data: cell}
}

func (w *sqliteWriter) writeLeaf(pageNo, base int, cells []btreeCell) {
	p := w.page(pageNo)
	content := sqlitePageSize
	for i := len(cells) - 1; i >= 0; i-- {
		content -= len(cells[i].data)
		copy(p[content:], cells[i].data)
	}
	p[base] = pageTypeLeafTable
	binary.BigEndian.PutUint16(p[base+1:], 0)
	binary.BigEndian.PutUint16(p[base+3:], uint16(len(cells)))
	binary.BigEndian.PutUint16(p[base+5:], uint16(content))
	p[base+7] = 0
	// cell pointer array, ascending by rowid
	off := content
	for i, c := range cells {
		binary.BigEndian.PutUint16(p[base+8+2*i:], uint16(off))
		off += len(c.data)
	}
}

func leafFits(base, nCells, totalBytes int) bool {
	return base+8+2*nCells+totalBytes <= sqlitePageSize
}

// writeTree lays out cells as a rowid b-tree and returns the root page number.
// When fixedRoot is non-zero the root must be that page (used for page 1, the
// sqlite_schema root, which also carries the 100-byte file header).
func (w *sqliteWriter) writeTree(cells []btreeCell, fixedRoot, base int) (int, error) {
	// Split into leaf-sized chunks.
	var chunks [][]btreeCell
	cur := []btreeCell{}
	total := 0
	chunkBase := base
	for _, c := range cells {
		if len(cur) > 0 && !leafFits(chunkBase, len(cur)+1, total+len(c.data)) {
			chunks = append(chunks, cur)
			cur, total, chunkBase = []btreeCell{}, 0, 0
		}
		cur = append(cur, c)
		total += len(c.data)
	}
	chunks = append(chunks, cur)

	if len(chunks) == 1 {
		root := fixedRoot
		if root == 0 {
			root = w.newPage()
		}
		w.writeLeaf(root, base, chunks[0])
		return root, nil
	}
	if fixedRoot != 0 {
		return 0, errors.New("schema table does not fit on page 1")
	}

	leaves := make([]int, 0, len(chunks))
	for _, chunk := range chunks {
		pg := w.newPage()
		w.writeLeaf(pg, 0, chunk)
		leaves = append(leaves, pg)
	}
	root := w.newPage()
	p := w.page(root)
	interior := make([][]byte, 0, len(leaves)-1)
	for i := 0; i < len(leaves)-1; i++ {
		cell := make([]byte, 4)
		binary.BigEndian.PutUint32(cell, uint32(leaves[i]))
		last := chunks[i][len(chunks[i])-1].rowid
		cell = append(cell, encVarint(uint64(last))...)
		interior = append(interior, cell)
	}
	content := sqlitePageSize
	for i := len(interior) - 1; i >= 0; i-- {
		content -= len(interior[i])
		copy(p[content:], interior[i])
	}
	if 12+2*len(interior)+(sqlitePageSize-content) > sqlitePageSize {
		return 0, errors.New("table too large for a two-level b-tree")
	}
	p[0] = pageTypeIntTable
	binary.BigEndian.PutUint16(p[1:], 0)
	binary.BigEndian.PutUint16(p[3:], uint16(len(interior)))
	binary.BigEndian.PutUint16(p[5:], uint16(content))
	p[7] = 0
	binary.BigEndian.PutUint32(p[8:], uint32(leaves[len(leaves)-1]))
	off := content
	for i, c := range interior {
		binary.BigEndian.PutUint16(p[12+2*i:], uint16(off))
		off += len(c)
	}
	return root, nil
}

// sqliteTable is one rowid table to materialize into the database file.
type sqliteTable struct {
	Name string
	SQL  string
	Rows [][]any
}

// writeDatabase renders the whole database and atomically replaces path.
func writeDatabase(path string, tables []sqliteTable) error {
	w := &sqliteWriter{}
	w.newPage() // page 1: file header + sqlite_schema root

	schemaRows := make([][]any, 0, len(tables))
	for _, t := range tables {
		cells := make([]btreeCell, 0, len(t.Rows))
		for i, row := range t.Rows {
			payload, err := encodeRecord(row)
			if err != nil {
				return err
			}
			cells = append(cells, w.makeCell(int64(i+1), payload))
		}
		root, err := w.writeTree(cells, 0, 0)
		if err != nil {
			return err
		}
		schemaRows = append(schemaRows, []any{"table", t.Name, t.Name, int64(root), t.SQL})
	}

	schemaCells := make([]btreeCell, 0, len(schemaRows))
	for i, row := range schemaRows {
		payload, err := encodeRecord(row)
		if err != nil {
			return err
		}
		schemaCells = append(schemaCells, w.makeCell(int64(i+1), payload))
	}
	if _, err := w.writeTree(schemaCells, 1, 100); err != nil {
		return err
	}

	h := w.page(1)
	copy(h, []byte("SQLite format 3\x00"))
	binary.BigEndian.PutUint16(h[16:], uint16(sqlitePageSize))
	h[18], h[19] = 1, 1 // legacy journal read/write versions
	h[20] = 0           // reserved bytes per page
	h[21], h[22], h[23] = 64, 32, 32
	binary.BigEndian.PutUint32(h[24:], 1)                    // file change counter
	binary.BigEndian.PutUint32(h[28:], uint32(len(w.pages))) // database size in pages
	binary.BigEndian.PutUint32(h[32:], 0)                    // freelist trunk page
	binary.BigEndian.PutUint32(h[36:], 0)                    // freelist page count
	binary.BigEndian.PutUint32(h[40:], 1)                    // schema cookie
	binary.BigEndian.PutUint32(h[44:], 4)                    // schema format number
	binary.BigEndian.PutUint32(h[48:], 0)                    // default page cache size
	binary.BigEndian.PutUint32(h[52:], 0)                    // largest root b-tree page
	binary.BigEndian.PutUint32(h[56:], 1)                    // text encoding: UTF-8
	binary.BigEndian.PutUint32(h[60:], 0)                    // user version
	binary.BigEndian.PutUint32(h[64:], 0)                    // incremental vacuum
	binary.BigEndian.PutUint32(h[68:], 0)                    // application id
	binary.BigEndian.PutUint32(h[92:], 1)                    // version-valid-for
	binary.BigEndian.PutUint32(h[96:], uint32(sqliteVersionNum))

	buf := make([]byte, 0, len(w.pages)*sqlitePageSize)
	for _, p := range w.pages {
		buf = append(buf, p...)
	}

	// Write-then-rename so a reader never observes a half-written database.
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, buf, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// ---------- reader ----------

type sqliteReader struct {
	data     []byte
	pageSize int
}

func openDatabase(path string) (*sqliteReader, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if len(data) < 100 || string(data[:16]) != "SQLite format 3\x00" {
		return nil, errors.New("not a sqlite database")
	}
	ps := int(binary.BigEndian.Uint16(data[16:]))
	if ps == 1 {
		ps = 65536
	}
	if ps < 512 || len(data)%ps != 0 {
		return nil, errors.New("bad page size")
	}
	return &sqliteReader{data: data, pageSize: ps}, nil
}

func (r *sqliteReader) page(n int) ([]byte, error) {
	if n < 1 || n*r.pageSize > len(r.data) {
		return nil, fmt.Errorf("page %d out of range", n)
	}
	return r.data[(n-1)*r.pageSize : n*r.pageSize], nil
}

// payloadOf reassembles a cell payload, following any overflow chain.
func (r *sqliteReader) payloadOf(cell []byte) ([]byte, error) {
	total, n := decVarint(cell)
	if n == 0 {
		return nil, errors.New("corrupt cell")
	}
	off := n
	_, n = decVarint(cell[off:]) // rowid
	if n == 0 {
		return nil, errors.New("corrupt cell rowid")
	}
	off += n

	local := localPayloadSize(int(total), r.pageSize)
	if off+local > len(cell) {
		return nil, errors.New("truncated cell payload")
	}
	payload := append([]byte{}, cell[off:off+local]...)
	if local < int(total) {
		if off+local+4 > len(cell) {
			return nil, errors.New("missing overflow pointer")
		}
		next := int(binary.BigEndian.Uint32(cell[off+local:]))
		remaining := int(total) - local
		for remaining > 0 && next != 0 {
			p, err := r.page(next)
			if err != nil {
				return nil, err
			}
			n := min(r.pageSize-4, remaining)
			payload = append(payload, p[4:4+n]...)
			remaining -= n
			next = int(binary.BigEndian.Uint32(p[0:4]))
		}
		if remaining != 0 {
			return nil, errors.New("truncated overflow chain")
		}
	}
	return payload, nil
}

// walk visits every row of the rowid b-tree rooted at pageNo.
func (r *sqliteReader) walk(pageNo int, visit func([]any) error) error {
	p, err := r.page(pageNo)
	if err != nil {
		return err
	}
	base := 0
	if pageNo == 1 {
		base = 100
	}
	switch p[base] {
	case pageTypeLeafTable:
		nCells := int(binary.BigEndian.Uint16(p[base+3:]))
		for i := 0; i < nCells; i++ {
			off := int(binary.BigEndian.Uint16(p[base+8+2*i:]))
			if off <= 0 || off >= r.pageSize {
				return errors.New("bad cell pointer")
			}
			payload, err := r.payloadOf(p[off:])
			if err != nil {
				return err
			}
			vals, err := decodeRecord(payload)
			if err != nil {
				return err
			}
			if err := visit(vals); err != nil {
				return err
			}
		}
	case pageTypeIntTable:
		nCells := int(binary.BigEndian.Uint16(p[base+3:]))
		for i := 0; i < nCells; i++ {
			off := int(binary.BigEndian.Uint16(p[base+12+2*i:]))
			if off <= 0 || off+4 > r.pageSize {
				return errors.New("bad interior cell pointer")
			}
			child := int(binary.BigEndian.Uint32(p[off:]))
			if err := r.walk(child, visit); err != nil {
				return err
			}
		}
		right := int(binary.BigEndian.Uint32(p[base+8:]))
		if right != 0 {
			return r.walk(right, visit)
		}
	default:
		return fmt.Errorf("unsupported page type 0x%02x", p[base])
	}
	return nil
}

// tableRoots reads sqlite_schema and maps table name to root page.
func (r *sqliteReader) tableRoots() (map[string]int, error) {
	roots := map[string]int{}
	err := r.walk(1, func(vals []any) error {
		if len(vals) < 4 {
			return nil
		}
		typ, _ := vals[0].(string)
		name, _ := vals[1].(string)
		root, _ := vals[3].(int64)
		if typ == "table" && root > 0 {
			roots[name] = int(root)
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	return roots, nil
}

// selectAll returns every row of a table, or nil when the table is absent.
func (r *sqliteReader) selectAll(table string) ([][]any, error) {
	roots, err := r.tableRoots()
	if err != nil {
		return nil, err
	}
	root, ok := roots[table]
	if !ok {
		return nil, nil
	}
	var rows [][]any
	err = r.walk(root, func(vals []any) error {
		rows = append(rows, vals)
		return nil
	})
	if err != nil {
		return nil, err
	}
	return rows, nil
}
