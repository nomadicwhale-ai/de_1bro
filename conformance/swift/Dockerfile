FROM swift:5.10
WORKDIR /app
COPY main.swift .
RUN swiftc -O main.swift -o conf
CMD ["./conf"]
