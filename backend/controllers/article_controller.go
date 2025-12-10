package controllers

import (
	"context"
	"encoding/json"
	"encoding/xml"
	"errors"
	"io"
	"net/http"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/JerryLinyx/FinGOAT/global"
	"github.com/JerryLinyx/FinGOAT/models"
	"github.com/gin-gonic/gin"
	"github.com/go-redis/redis/v8"
	"gorm.io/gorm"
)

var cacheKey = "articles"
var httpClient = &http.Client{Timeout: 10 * time.Second}

type rssFeedDef struct {
	Name string
	URL  string
}

var defaultRSSFeeds = []rssFeedDef{
	{Name: "arXiv – 人工智能 (cs.AI)", URL: "https://export.arxiv.org/rss/cs.AI"},
	{Name: "机器之心 (Synced)", URL: "https://www.jiqizhixin.com/rss"},
	{Name: "量子位 (QbitAI)", URL: "https://www.qbitai.com/feed"},
	{Name: "谷歌 AI 博客", URL: "https://ai.googleblog.com/feeds/posts/default?alt=rss"},
}

type rssItem struct {
	Title       string
	Link        string
	Description string
	PublishedAt *time.Time
	GUID        string
}

type rssEnvelope struct {
	Channel struct {
		Items []struct {
			Title       string `xml:"title"`
			Link        string `xml:"link"`
			Description string `xml:"description"`
			GUID        string `xml:"guid"`
			PubDate     string `xml:"pubDate"`
		} `xml:"item"`
	} `xml:"channel"`
}

type atomLink struct {
	Href string `xml:"href,attr"`
}

type atomEnvelope struct {
	Entries []struct {
		Title     string     `xml:"title"`
		Links     []atomLink `xml:"link"`
		Summary   string     `xml:"summary"`
		Content   string     `xml:"content"`
		ID        string     `xml:"id"`
		Updated   string     `xml:"updated"`
		Published string     `xml:"published"`
	} `xml:"entry"`
}

var htmlTagRegex = regexp.MustCompile("<[^>]*>")

func parseTimeString(value string) *time.Time {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	layouts := []string{
		time.RFC3339,
		time.RFC3339Nano,
		time.RFC1123Z,
		time.RFC1123,
		time.RFC850,
		"Mon, 02 Jan 2006 15:04:05 -0700",
		"Mon, 2 Jan 2006 15:04:05 -0700",
	}
	for _, layout := range layouts {
		if t, err := time.Parse(layout, value); err == nil {
			return &t
		}
	}
	return nil
}

func sanitize(text string) string {
	clean := htmlTagRegex.ReplaceAllString(text, "")
	clean = strings.ReplaceAll(clean, "\n", " ")
	clean = strings.ReplaceAll(clean, "\r", " ")
	return strings.TrimSpace(clean)
}

func truncate(text string, maxLen int) string {
	if len(text) <= maxLen {
		return text
	}
	if maxLen <= 3 {
		return text[:maxLen]
	}
	return text[:maxLen-3] + "..."
}

func ensureDefaultFeeds(ctx context.Context) error {
	for _, f := range defaultRSSFeeds {
		feed := models.RSSFeed{
			Name: f.Name,
			URL:  f.URL,
		}
		if err := global.DB.WithContext(ctx).
			Where("url = ?", f.URL).
			Assign(models.RSSFeed{Name: f.Name, Active: true}).
			FirstOrCreate(&feed).Error; err != nil {
			return err
		}
	}
	return nil
}

func parseRSS(data []byte) ([]rssItem, error) {
	var rss rssEnvelope
	if err := xml.Unmarshal(data, &rss); err != nil {
		return nil, err
	}

	items := make([]rssItem, 0, len(rss.Channel.Items))
	for _, it := range rss.Channel.Items {
		link := strings.TrimSpace(it.Link)
		title := strings.TrimSpace(it.Title)
		if link == "" || title == "" {
			continue
		}
		items = append(items, rssItem{
			Title:       title,
			Link:        link,
			Description: it.Description,
			PublishedAt: parseTimeString(it.PubDate),
			GUID:        strings.TrimSpace(it.GUID),
		})
	}
	return items, nil
}

func parseAtom(data []byte) ([]rssItem, error) {
	var atom atomEnvelope
	if err := xml.Unmarshal(data, &atom); err != nil {
		return nil, err
	}

	items := make([]rssItem, 0, len(atom.Entries))
	for _, entry := range atom.Entries {
		link := ""
		for _, l := range entry.Links {
			if strings.TrimSpace(l.Href) != "" {
				link = strings.TrimSpace(l.Href)
				break
			}
		}
		if link == "" {
			continue
		}
		title := strings.TrimSpace(entry.Title)
		if title == "" {
			continue
		}
		published := parseTimeString(entry.Published)
		if published == nil {
			published = parseTimeString(entry.Updated)
		}
		desc := entry.Summary
		if desc == "" {
			desc = entry.Content
		}
		items = append(items, rssItem{
			Title:       title,
			Link:        link,
			Description: desc,
			PublishedAt: published,
			GUID:        strings.TrimSpace(entry.ID),
		})
	}
	return items, nil
}

func fetchLatestFeedItem(ctx context.Context, feed models.RSSFeed) (*rssItem, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, feed.URL, nil)
	if err != nil {
		return nil, err
	}

	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	data, err := io.ReadAll(io.LimitReader(resp.Body, 2<<20)) // limit to 2MB
	if err != nil {
		return nil, err
	}

	var root struct {
		XMLName xml.Name
	}
	if err := xml.Unmarshal(data, &root); err != nil {
		return nil, err
	}

	var items []rssItem
	switch strings.ToLower(root.XMLName.Local) {
	case "feed": // Atom
		items, err = parseAtom(data)
	default: // assume RSS if not Atom
		items, err = parseRSS(data)
	}
	if err != nil {
		return nil, err
	}
	if len(items) == 0 {
		return nil, nil
	}

	// Sort newest first by PublishedAt if available, otherwise keep feed order
	sort.SliceStable(items, func(i, j int) bool {
		if items[i].PublishedAt == nil {
			return false
		}
		if items[j].PublishedAt == nil {
			return true
		}
		return items[i].PublishedAt.After(*items[j].PublishedAt)
	})

	return &items[0], nil
}

func CreateArticle(c *gin.Context) {
	var article models.Article
	if err := c.ShouldBindJSON(&article); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if err := global.DB.AutoMigrate(&models.Article{}, &models.RSSFeed{}); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	if err := global.DB.Create(&article).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	// 缓存失效：异步/不阻断主流程
	go func() {
		_ = global.RedisDB.Del(c.Request.Context(), cacheKey).Err()
	}()

	c.JSON(http.StatusCreated, article)
}

func GetArticles(c *gin.Context) {

	var articles []models.Article
	ctx := c.Request.Context()

	if cachedData, err := global.RedisDB.Get(ctx, cacheKey).Result(); err == nil {
		if err := json.Unmarshal([]byte(cachedData), &articles); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
	} else if err == redis.Nil {
		if err := global.DB.Order("COALESCE(published_at, created_at) DESC").Limit(50).Find(&articles).Error; err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		articlesJSON, err := json.Marshal(articles)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		if err := global.RedisDB.Set(ctx, cacheKey, articlesJSON, 10*time.Minute).Err(); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
	} else {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, articles)
}

// RefreshRSSArticles pulls the latest item from each configured RSS feed and inserts if new.
func RefreshRSSArticles(c *gin.Context) {
	ctx := c.Request.Context()

	if err := ensureDefaultFeeds(ctx); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to ensure default feeds: " + err.Error()})
		return
	}

	var feeds []models.RSSFeed
	if err := global.DB.WithContext(ctx).Where("active = ?", true).Find(&feeds).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	inserted := []models.Article{}
	warnings := []string{}

	for _, feed := range feeds {
		item, err := fetchLatestFeedItem(ctx, feed)
		if err != nil {
			warnings = append(warnings, feed.Name+": "+err.Error())
			continue
		}
		if item == nil {
			continue
		}

		// Deduplicate by link or GUID
		var existing models.Article
		err = global.DB.WithContext(ctx).
			Where("link = ? OR (guid <> '' AND guid = ?)", item.Link, item.GUID).
			First(&existing).Error
		if err == nil {
			continue // already stored
		}
		if err != nil && !errors.Is(err, gorm.ErrRecordNotFound) {
			warnings = append(warnings, feed.Name+": "+err.Error())
			continue
		}

		cleanContent := sanitize(item.Description)
		if cleanContent == "" {
			cleanContent = item.Title
		}
		preview := truncate(cleanContent, 280)

		newArticle := models.Article{
			Title:       item.Title,
			Content:     cleanContent,
			Preview:     preview,
			Source:      feed.Name,
			SourceURL:   feed.URL,
			Link:        item.Link,
			GUID:        item.GUID,
			PublishedAt: item.PublishedAt,
		}

		if err := global.DB.WithContext(ctx).Create(&newArticle).Error; err != nil {
			warnings = append(warnings, feed.Name+": "+err.Error())
			continue
		}
		inserted = append(inserted, newArticle)

		now := time.Now()
		_ = global.DB.WithContext(ctx).Model(&models.RSSFeed{}).
			Where("id = ?", feed.ID).
			Update("last_fetched", &now).Error
	}

	// Invalidate cached articles to reflect fresh entries
	go func() {
		_ = global.RedisDB.Del(context.Background(), cacheKey).Err()
	}()

	c.JSON(http.StatusOK, gin.H{
		"inserted": len(inserted),
		"articles": inserted,
		"warnings": warnings,
	})
}

func GetArticlesByID(c *gin.Context) {
	id := c.Param("id")
	var article models.Article
	if err := global.DB.Where("id = ?", id).First(&article).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			c.JSON(http.StatusNotFound, gin.H{"error": err.Error()})
		} else {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		}
		return
	}
	c.JSON(http.StatusOK, article)
}
