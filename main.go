package main

import (
	"github.com/JerryLinyx/FinGOAT/config"
	"github.com/JerryLinyx/FinGOAT/router"
)

func main() {
	config.InitConfig()
	// fmt.Println(config.AppConfig)

	r := router.InitRouter()
	r.Run(config.AppConfig.App.Port)
}
