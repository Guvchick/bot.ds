package main

import (
	"archive/zip"
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"mime/multipart"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/robfig/cron/v3"
)

// ─── helpers ──────────────────────────────────────────────────────────────────

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]string{"error": msg})
}

// ─── store ────────────────────────────────────────────────────────────────────

type Store struct{ db *sql.DB }

func newStore() (*Store, error) {
	dsn := fmt.Sprintf(
		"host=%s port=%s dbname=%s user=%s password=%s sslmode=disable",
		env("POSTGRES_HOST", "db"),
		env("POSTGRES_PORT", "5432"),
		env("POSTGRES_DB", "elixbot"),
		env("POSTGRES_USER", "elixbot"),
		env("POSTGRES_PASSWORD", ""),
	)
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(5)
	return &Store{db: db}, nil
}

func (s *Store) init(ctx context.Context) error {
	_, err := s.db.ExecContext(ctx, `
		CREATE TABLE IF NOT EXISTS settings (
			guild_id TEXT NOT NULL,
			key      TEXT NOT NULL,
			value    TEXT,
			PRIMARY KEY (guild_id, key)
		);
		CREATE TABLE IF NOT EXISTS users (
			user_id    TEXT   NOT NULL,
			guild_id   TEXT   NOT NULL,
			xp         BIGINT DEFAULT 0,
			level      INT    DEFAULT 0,
			messages   INT    DEFAULT 0,
			voice_time BIGINT DEFAULT 0,
			PRIMARY KEY (user_id, guild_id)
		);
	`)
	return err
}

// ── settings ──────────────────────────────────────────────────────────────────

func (s *Store) getSetting(ctx context.Context, guildID, key string) (string, bool, error) {
	var v string
	err := s.db.QueryRowContext(ctx,
		"SELECT value FROM settings WHERE guild_id=$1 AND key=$2", guildID, key,
	).Scan(&v)
	if err == sql.ErrNoRows {
		return "", false, nil
	}
	return v, err == nil, err
}

func (s *Store) getAllSettings(ctx context.Context, guildID string) (map[string]string, error) {
	rows, err := s.db.QueryContext(ctx,
		"SELECT key, value FROM settings WHERE guild_id=$1", guildID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	m := make(map[string]string)
	for rows.Next() {
		var k, v string
		if err := rows.Scan(&k, &v); err != nil {
			return nil, err
		}
		m[k] = v
	}
	return m, rows.Err()
}

func (s *Store) setSetting(ctx context.Context, guildID, key, value string) error {
	_, err := s.db.ExecContext(ctx,
		`INSERT INTO settings(guild_id,key,value) VALUES($1,$2,$3)
		 ON CONFLICT(guild_id,key) DO UPDATE SET value=EXCLUDED.value`,
		guildID, key, value,
	)
	return err
}

func (s *Store) deleteSetting(ctx context.Context, guildID, key string) error {
	_, err := s.db.ExecContext(ctx,
		"DELETE FROM settings WHERE guild_id=$1 AND key=$2", guildID, key,
	)
	return err
}

// ── users ─────────────────────────────────────────────────────────────────────

type UserStats struct {
	UserID    string `json:"user_id"`
	GuildID   string `json:"guild_id"`
	XP        int64  `json:"xp"`
	Level     int    `json:"level"`
	Messages  int    `json:"messages"`
	VoiceTime int64  `json:"voice_time"`
}

type XPResult struct {
	Level   int  `json:"level"`
	LevelUp bool `json:"level_up"`
}

func xpForLevel(level int) int64 { return int64(300 * (level + 1)) }

func (s *Store) getUser(ctx context.Context, userID, guildID string) (*UserStats, error) {
	u := &UserStats{UserID: userID, GuildID: guildID}
	err := s.db.QueryRowContext(ctx,
		"SELECT xp,level,messages,voice_time FROM users WHERE user_id=$1 AND guild_id=$2",
		userID, guildID,
	).Scan(&u.XP, &u.Level, &u.Messages, &u.VoiceTime)
	if err == sql.ErrNoRows {
		_, err = s.db.ExecContext(ctx,
			"INSERT INTO users(user_id,guild_id) VALUES($1,$2) ON CONFLICT DO NOTHING",
			userID, guildID,
		)
		return u, err
	}
	return u, err
}

func (s *Store) addXP(ctx context.Context, userID, guildID string, amount int64) (*XPResult, error) {
	var xp int64
	var level int
	err := s.db.QueryRowContext(ctx,
		`INSERT INTO users(user_id,guild_id,xp,level,messages,voice_time) VALUES($1,$2,$3,0,0,0)
		 ON CONFLICT(user_id,guild_id) DO UPDATE SET xp=users.xp+$3
		 RETURNING xp, level`,
		userID, guildID, amount,
	).Scan(&xp, &level)
	if err != nil {
		return nil, err
	}
	newLevel := level
	for xp >= xpForLevel(newLevel) {
		newLevel++
	}
	res := &XPResult{Level: newLevel, LevelUp: newLevel > level}
	if newLevel > level {
		_, err = s.db.ExecContext(ctx,
			"UPDATE users SET level=$1 WHERE user_id=$2 AND guild_id=$3",
			newLevel, userID, guildID,
		)
	}
	return res, err
}

func (s *Store) incrMessages(ctx context.Context, userID, guildID string) error {
	_, err := s.db.ExecContext(ctx,
		`INSERT INTO users(user_id,guild_id,xp,level,messages,voice_time) VALUES($1,$2,0,0,1,0)
		 ON CONFLICT(user_id,guild_id) DO UPDATE SET messages=users.messages+1`,
		userID, guildID,
	)
	return err
}

func (s *Store) addVoiceTime(ctx context.Context, userID, guildID string, seconds int64) error {
	_, err := s.db.ExecContext(ctx,
		`INSERT INTO users(user_id,guild_id,xp,level,messages,voice_time) VALUES($1,$2,0,0,0,$3)
		 ON CONFLICT(user_id,guild_id) DO UPDATE SET voice_time=users.voice_time+$3`,
		userID, guildID, seconds,
	)
	return err
}

func (s *Store) leaderboard(ctx context.Context, guildID string, limit int) ([]UserStats, error) {
	rows, err := s.db.QueryContext(ctx,
		`SELECT user_id,xp,level,messages,voice_time FROM users
		 WHERE guild_id=$1 ORDER BY level DESC, xp DESC LIMIT $2`,
		guildID, limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var result []UserStats
	for rows.Next() {
		u := UserStats{GuildID: guildID}
		if err := rows.Scan(&u.UserID, &u.XP, &u.Level, &u.Messages, &u.VoiceTime); err != nil {
			return nil, err
		}
		result = append(result, u)
	}
	return result, rows.Err()
}

// ─── backup ───────────────────────────────────────────────────────────────────

func doBackup(logger *log.Logger) {
	channelID := env("BACKUP_CHANNEL_ID", "")
	token := env("DISCORD_TOKEN", "")
	if channelID == "" || token == "" {
		logger.Println("[backup] BACKUP_CHANNEL_ID or DISCORD_TOKEN not set — skipped")
		return
	}

	logger.Println("[backup] Starting database backup...")

	cmd := exec.Command("pg_dump",
		"-h", env("POSTGRES_HOST", "db"),
		"-p", env("POSTGRES_PORT", "5432"),
		"-U", env("POSTGRES_USER", "elixbot"),
		"-d", env("POSTGRES_DB", "elixbot"),
		"--no-password",
	)
	cmd.Env = append(os.Environ(), "PGPASSWORD="+env("POSTGRES_PASSWORD", ""))

	dumpData, err := cmd.Output()
	if err != nil {
		logger.Printf("[backup] pg_dump failed: %v", err)
		return
	}

	// Pack into ZIP
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	sqlName := fmt.Sprintf("elixbot-%s.sql", time.Now().Format("2006-01-02_15-04-05"))
	fw, err := zw.Create(sqlName)
	if err != nil {
		logger.Printf("[backup] zip create: %v", err)
		return
	}
	if _, err = fw.Write(dumpData); err != nil {
		logger.Printf("[backup] zip write: %v", err)
		return
	}
	zw.Close()

	zipName := strings.TrimSuffix(sqlName, ".sql") + ".zip"
	logger.Printf("[backup] Archive: %s (%d bytes)", zipName, buf.Len())

	if err := sendToDiscord(token, channelID, zipName, buf.Bytes()); err != nil {
		logger.Printf("[backup] Discord upload failed: %v", err)
		return
	}
	logger.Printf("[backup] Sent to Discord channel %s", channelID)
}

func sendToDiscord(token, channelID, filename string, data []byte) error {
	var body bytes.Buffer
	mw := multipart.NewWriter(&body)

	fw, err := mw.CreateFormFile("file", filename)
	if err != nil {
		return err
	}
	if _, err = fw.Write(data); err != nil {
		return err
	}

	cf, err := mw.CreateFormField("content")
	if err != nil {
		return err
	}
	cf.Write([]byte(fmt.Sprintf(
		"📦 **Резервная копия БД** `%s`",
		time.Now().Format("02.01.2006 15:04:05"),
	)))
	mw.Close()

	url := fmt.Sprintf("https://discord.com/api/v10/channels/%s/messages", channelID)
	req, err := http.NewRequest("POST", url, &body)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bot "+token)
	req.Header.Set("Content-Type", mw.FormDataContentType())

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("discord API %d: %s", resp.StatusCode, b)
	}
	return nil
}

// ─── HTTP handlers ────────────────────────────────────────────────────────────

type Server struct {
	store  *Store
	logger *log.Logger
}

func (srv *Server) routes() http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /health", srv.health)

	mux.HandleFunc("GET /settings/{guildID}", srv.getAllSettings)
	mux.HandleFunc("GET /settings/{guildID}/{key}", srv.getSetting)
	mux.HandleFunc("PUT /settings/{guildID}/{key}", srv.setSetting)
	mux.HandleFunc("DELETE /settings/{guildID}/{key}", srv.deleteSetting)

	mux.HandleFunc("GET /users/{guildID}/{userID}", srv.getUser)
	mux.HandleFunc("POST /users/{guildID}/{userID}/xp", srv.addXP)
	mux.HandleFunc("POST /users/{guildID}/{userID}/messages", srv.incrMessages)
	mux.HandleFunc("POST /users/{guildID}/{userID}/voice", srv.addVoiceTime)

	mux.HandleFunc("GET /leaderboard/{guildID}", srv.getLeaderboard)
	mux.HandleFunc("POST /backup", srv.triggerBackup)

	return mux
}

func (srv *Server) health(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, map[string]string{"status": "ok"})
}

func (srv *Server) getAllSettings(w http.ResponseWriter, r *http.Request) {
	m, err := srv.store.getAllSettings(r.Context(), r.PathValue("guildID"))
	if err != nil {
		srv.logger.Printf("getAllSettings: %v", err)
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, m)
}

func (srv *Server) getSetting(w http.ResponseWriter, r *http.Request) {
	v, ok, err := srv.store.getSetting(r.Context(), r.PathValue("guildID"), r.PathValue("key"))
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	if !ok {
		writeErr(w, 404, "not found")
		return
	}
	writeJSON(w, 200, map[string]string{"value": v})
}

func (srv *Server) setSetting(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Value string `json:"value"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeErr(w, 400, "invalid json")
		return
	}
	if err := srv.store.setSetting(r.Context(), r.PathValue("guildID"), r.PathValue("key"), body.Value); err != nil {
		srv.logger.Printf("setSetting: %v", err)
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]string{"status": "ok"})
}

func (srv *Server) deleteSetting(w http.ResponseWriter, r *http.Request) {
	if err := srv.store.deleteSetting(r.Context(), r.PathValue("guildID"), r.PathValue("key")); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]string{"status": "ok"})
}

func (srv *Server) getUser(w http.ResponseWriter, r *http.Request) {
	u, err := srv.store.getUser(r.Context(), r.PathValue("userID"), r.PathValue("guildID"))
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, u)
}

func (srv *Server) addXP(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Amount int64 `json:"amount"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeErr(w, 400, "invalid json")
		return
	}
	res, err := srv.store.addXP(r.Context(), r.PathValue("userID"), r.PathValue("guildID"), body.Amount)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, res)
}

func (srv *Server) incrMessages(w http.ResponseWriter, r *http.Request) {
	if err := srv.store.incrMessages(r.Context(), r.PathValue("userID"), r.PathValue("guildID")); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]string{"status": "ok"})
}

func (srv *Server) addVoiceTime(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Seconds int64 `json:"seconds"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeErr(w, 400, "invalid json")
		return
	}
	if err := srv.store.addVoiceTime(r.Context(), r.PathValue("userID"), r.PathValue("guildID"), body.Seconds); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]string{"status": "ok"})
}

func (srv *Server) getLeaderboard(w http.ResponseWriter, r *http.Request) {
	limit := 10
	if l := r.URL.Query().Get("limit"); l != "" {
		if n, err := strconv.Atoi(l); err == nil && n > 0 {
			limit = n
		}
	}
	board, err := srv.store.leaderboard(r.Context(), r.PathValue("guildID"), limit)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	if board == nil {
		board = []UserStats{}
	}
	writeJSON(w, 200, board)
}

func (srv *Server) triggerBackup(w http.ResponseWriter, r *http.Request) {
	go doBackup(srv.logger)
	writeJSON(w, 202, map[string]string{"status": "backup started"})
}

// ─── logging ──────────────────────────────────────────────────────────────────

func setupLogger() (*log.Logger, func()) {
	if err := os.MkdirAll("logs", 0755); err != nil {
		log.Fatal(err)
	}
	f, err := os.OpenFile("logs/db-service.txt",
		os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644,
	)
	if err != nil {
		log.Fatal(err)
	}
	logger := log.New(io.MultiWriter(os.Stdout, f), "", log.LstdFlags)
	return logger, func() { f.Close() }
}

// ─── main ─────────────────────────────────────────────────────────────────────

func main() {
	logger, cleanup := setupLogger()
	defer cleanup()

	store, err := newStore()
	if err != nil {
		logger.Fatalf("DB open: %v", err)
	}

	// Wait for PostgreSQL
	ctx := context.Background()
	for i := 1; i <= 15; i++ {
		if err = store.db.PingContext(ctx); err == nil {
			break
		}
		logger.Printf("Waiting for DB (%d/15): %v", i, err)
		time.Sleep(2 * time.Second)
	}
	if err != nil {
		logger.Fatalf("Cannot connect to DB: %v", err)
	}

	if err := store.init(ctx); err != nil {
		logger.Fatalf("DB init: %v", err)
	}
	logger.Println("Database initialized")

	// Backup scheduler
	cronExpr := env("BACKUP_CRON", "0 3 * * *")
	c := cron.New()
	if _, err := c.AddFunc(cronExpr, func() { doBackup(logger) }); err != nil {
		logger.Printf("Invalid BACKUP_CRON %q: %v — scheduler disabled", cronExpr, err)
	} else {
		c.Start()
		logger.Printf("Backup scheduler started (cron: %s)", cronExpr)
		defer c.Stop()
	}

	srv := &Server{store: store, logger: logger}
	port := env("DB_SERVICE_PORT", "8080")
	logger.Printf("Listening on :%s", port)

	if err := http.ListenAndServe(":"+port, srv.routes()); err != nil {
		logger.Fatalf("Server: %v", err)
	}
}
