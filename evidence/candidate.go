package main
import ("encoding/json"; "os")
func deliver(allowed bool, events *[]string) string {
	if !allowed {
		return "access_revoked"
	}
	*events = append(*events, "audit", "release")
	return "exported"
}
func main() {
  var input struct { Allowed bool `json:"allowed"` }
  if json.NewDecoder(os.Stdin).Decode(&input) != nil { os.Exit(2) }
  events := []string{}
  status := deliver(input.Allowed, &events)
  json.NewEncoder(os.Stdout).Encode(map[string]interface{}{"status":status,"events":events})
}
