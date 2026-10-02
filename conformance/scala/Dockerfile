FROM sbtscala/scala-sbt:eclipse-temurin-21.0.4_7_1.10.2_3.5.1
WORKDIR /app
COPY Main.scala .
RUN scala-cli --version >/dev/null 2>&1 || true
# scala-cli is bundled in recent sbtscala images; otherwise install the Scala 3 compiler distribution.
CMD ["scala-cli", "run", "Main.scala"]
