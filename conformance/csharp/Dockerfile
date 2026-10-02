FROM mcr.microsoft.com/dotnet/sdk:8.0
WORKDIR /app
COPY . .
RUN dotnet build -c Release -o out
CMD ["dotnet", "out/conformance.dll"]
