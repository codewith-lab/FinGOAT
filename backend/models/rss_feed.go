package models

import (
	"time"

	"gorm.io/gorm"
)

// RSSFeed defines an RSS/Atom source to ingest.
type RSSFeed struct {
	gorm.Model
	Name         string
	URL          string `gorm:"uniqueIndex"`
	Active       bool   `gorm:"default:true"`
	LastFetched  *time.Time
	LastItemGUID string
}
