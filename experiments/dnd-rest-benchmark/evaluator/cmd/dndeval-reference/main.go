package main

import (
	"fmt"
	"net/http"
	"os"

	"dndeval/internal/eval"
)

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	address := "127.0.0.1:" + port
	fmt.Fprintf(os.Stderr, "dndeval reference server listening on %s\n", address)
	if err := http.ListenAndServe(address, eval.ReferenceHandler()); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
