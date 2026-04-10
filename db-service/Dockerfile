FROM golang:1.22-alpine AS builder

RUN apk add --no-cache git

WORKDIR /app
COPY . .
RUN go mod tidy && go build -ldflags="-w -s" -o db-service .

# ── runtime ────────────────────────────────────────────────────────────────────
FROM alpine:3.19

# pg_dump для резервных копий
RUN apk add --no-cache postgresql16-client ca-certificates tzdata

WORKDIR /app
COPY --from=builder /app/db-service .
RUN mkdir -p logs

CMD ["./db-service"]
