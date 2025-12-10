package controllers

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

// Health provides an unauthenticated liveness endpoint for container orchestrators.
func Health(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":    "ok",
		"timestamp": time.Now().UTC(),
	})
}
