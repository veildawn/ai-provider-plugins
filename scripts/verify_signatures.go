package main

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

type publisher struct {
	Handle string `json:"handle"`
	Keys   []struct {
		KeyID     string `json:"key_id"`
		PublicKey string `json:"public_key"`
	} `json:"keys"`
}

func main() {
	keys := map[string]map[string]ed25519.PublicKey{}
	publisherPaths, _ := filepath.Glob("publishers/*.json")
	for _, path := range publisherPaths {
		raw, err := os.ReadFile(path)
		if err != nil {
			panic(err)
		}
		var pub publisher
		if err := json.Unmarshal(raw, &pub); err != nil {
			panic(err)
		}
		keys[pub.Handle] = map[string]ed25519.PublicKey{}
		for _, item := range pub.Keys {
			key, err := base64.StdEncoding.DecodeString(item.PublicKey)
			if err != nil {
				panic(err)
			}
			keys[pub.Handle][item.KeyID] = key
		}
	}
	paths, _ := filepath.Glob("plugins/*.json")
	for _, path := range paths {
		raw, err := os.ReadFile(path)
		if err != nil {
			panic(err)
		}
		var doc map[string]any
		if err := json.Unmarshal(raw, &doc); err != nil {
			panic(err)
		}
		sigDoc, ok := doc["signature"].(map[string]any)
		if !ok {
			panic(path + ": missing signature")
		}
		keyID, _ := sigDoc["key_id"].(string)
		encoded, _ := sigDoc["sig"].(string)
		publisherID, _ := doc["publisher"].(string)
		delete(doc, "signature")
		canonical, err := json.Marshal(doc)
		if err != nil {
			panic(err)
		}
		sig, err := base64.StdEncoding.DecodeString(encoded)
		if err != nil {
			panic(err)
		}
		key := keys[publisherID][keyID]
		if len(key) != ed25519.PublicKeySize || !ed25519.Verify(key, canonical, sig) {
			panic(path + ": invalid signature")
		}
	}
	fmt.Printf("verified %d signatures\n", len(paths))
}
