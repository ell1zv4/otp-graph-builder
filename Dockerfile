FROM eclipse-temurin:21-jre

WORKDIR /app

COPY otp.jar .
COPY graph ./graph

EXPOSE 8080

ENV JAVA_OPTS="-Xms2G -Xmx4G -XX:+UseG1GC -XX:+AlwaysPreTouch -XX:MaxGCPauseMillis=200"

CMD ["java",
  "-Xms2G",
  "-Xmx4G",
  "-XX:+UseG1GC",
  "-XX:+AlwaysPreTouch",
  "-XX:MaxGCPauseMillis=200",
  "-Dorg.opentripplanner.http.bindAddress=0.0.0.0",
  "-jar", "otp.jar",
  "--load", "graph",
  "--serve"
]
