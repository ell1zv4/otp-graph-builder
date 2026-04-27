FROM eclipse-temurin:25-jre

WORKDIR /app

COPY otp.jar .
COPY graph ./graph

EXPOSE 8080

CMD ["java",
  "-XX:MaxRAMPercentage=75",
  "-XX:+UseG1GC",
  "-XX:+AlwaysPreTouch",
  "-XX:+UseStringDeduplication",
  "-XX:+DisableExplicitGC",
  "-Dorg.opentripplanner.http.bindAddress=0.0.0.0",
  "-jar", "otp.jar",
  "--load", "graph"
]