FROM eclipse-temurin:21-jdk
RUN apt-get update && apt-get install -y curl unzip && \
    curl -sSL https://github.com/JetBrains/kotlin/releases/download/v2.0.20/kotlin-compiler-2.0.20.zip -o /tmp/k.zip && \
    unzip -q /tmp/k.zip -d /opt && rm /tmp/k.zip
ENV PATH="/opt/kotlinc/bin:${PATH}"
WORKDIR /app
COPY Main.kt .
RUN kotlinc Main.kt -include-runtime -d conf.jar
CMD ["java", "-jar", "conf.jar"]
