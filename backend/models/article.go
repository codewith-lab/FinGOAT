package models

import (
	"time"

	"gorm.io/gorm"
)

type Article struct {
	gorm.Model
	Title       string `binding:"required"`
	Content     string `binding:"required"`
	Preview     string `binding:"required"`
	Source      string `gorm:"index"`
	SourceURL   string
	Link        string     `gorm:"uniqueIndex"`
	GUID        string     `gorm:"index"`
	PublishedAt *time.Time `gorm:"index"`
}
