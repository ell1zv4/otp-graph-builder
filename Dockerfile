FROM eclipse-temurin:21-jre

WORKDIR /app

RUN curl -L https://repo1.maven.org/maven2/org/opentripplanner/otp/2.5.0/otp-2.5.0-shaded.jar -o otp.jar

EXPOSE 8080

CMD ["java",
  "-Xms4G",
  "-Xmx6G",
  "-XX:+UseG1GC",
  "-XX:MaxGCPauseMillis=200",
  "-XX:+AlwaysPreTouch",
  "-XX:+UseStringDeduplication",
  "-XX:+DisableExplicitGC",
  "-Dorg.opentripplanner.http.bindAddress=0.0.0.0",
  "-jar", "otp.jar",
  "--load", "graph",
  "--serve"
]
