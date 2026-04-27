FROM eclipse-temurin:21-jre

WORKDIR /app

RUN curl -L https://repo1.maven.org/maven2/org/opentripplanner/otp/2.5.0/otp-2.5.0-shaded.jar -o otp.jar

COPY graph ./graph

EXPOSE 8080

CMD java \
  -Xms2G -Xmx4G \
  -XX:+UseG1GC \
  -XX:+AlwaysPreTouch \
  -XX:MaxGCPauseMillis=200 \
  -Dorg.opentripplanner.http.bindAddress=0.0.0.0 \
  -jar otp.jar \
  --load graph \
  --serve
