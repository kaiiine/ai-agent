"""Go stack prompt."""

GO_PROMPT = """\
━━ STACK DÉTECTÉ : GO ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCAFFOLDING :
   go mod init <module>   puis créer main.go
   Framework : Echo, Gin, Fiber, Chi selon le contexte

FORMAT / VET (obligatoires avant toute vérif) :
   go fmt ./... && go vet ./...

ERREURS :
   • Toujours return error explicite avec contexte :
     fmt.Errorf("open config: %w", err)
   • Pas de panic() en code de prod sauf invariant impossible.

TESTS :
   go test -race ./...   (race detector TOUJOURS actif)
   go test -cover ./...  pour vérifier la couverture

BUILD :
   go build ./...

CONCURRENCE :
   • Préférer les channels aux mutex quand c'est naturel.
   • Toujours vérifier la fuite de goroutines (defer cancel() sur les contexts).

VÉRIFICATION :
   go fmt ./... && go vet ./... && go build ./... && go test -race ./...
"""
