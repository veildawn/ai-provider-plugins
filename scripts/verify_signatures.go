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

type revocation struct {
	Revoked []struct {
		KeyID string `json:"key_id"`
	} `json:"revoked"`
}

func main() {
	revoked := map[string]bool{}
	if raw, err := os.ReadFile("revoke.json"); err == nil {
		var doc revocation
		if err := json.Unmarshal(raw, &doc); err != nil {
			panic(err)
		}
		for _, item := range doc.Revoked {
			revoked[item.KeyID] = true
		}
	}
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
	if len(paths) == 0 {
		fmt.Println("plugins/ absent (build artifacts not committed) — nothing to verify")
		return
	}
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
		if revoked[keyID] {
			panic(path + ": signed with revoked key " + keyID)
		}
		key := keys[publisherID][keyID]
		if len(key) != ed25519.PublicKeySize || !ed25519.Verify(key, canonical, sig) {
			panic(path + ": invalid signature")
		}
	}
	fmt.Printf("verified %d signatures\n", len(paths))
}
