FROM eclipse-temurin:21-jre@sha256:010e0a06bd4e0184dec58626afb3ba727b42c56c91b977e2f0a9e0837e0fa3fb

WORKDIR /app

ARG OTP_VERSION=2.5.0
ARG OTP_SHA256=0c6d61d347706b0b90967a1cbe7109b22af3be4509168a7078db61ec91d4d7ab
RUN curl -fsSL "https://repo1.maven.org/maven2/org/opentripplanner/otp/${OTP_VERSION}/otp-${OTP_VERSION}-shaded.jar" -o otp.jar \
  && echo "${OTP_SHA256}  otp.jar" | sha256sum -c -

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
