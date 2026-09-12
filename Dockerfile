# ==========================================
# Stage 1: Build UniTime WAR from source
# ==========================================
FROM maven:3.9-eclipse-temurin-17 AS builder

WORKDIR /app

# Copy pom.xml and build config first to take advantage of Docker layer caching
COPY pom.xml ./
COPY build.number ./
COPY build.properties ./
COPY 3rd_party ./3rd_party
COPY JavaSource ./JavaSource
COPY WebContent ./WebContent

# Compile Java and GWT, package WAR file
ENV MAVEN_OPTS="-Xmx2048m"
RUN mvn clean package -DskipTests \
    -Dignore.symbol.file \
    -Dhttps.protocols=TLSv1.2,TLSv1.3 \
    -Dhttp.keepAlive=false \
    -Dmaven.wagon.http.pool=false \
    -Dgwt.localWorkers=2 \
    -Dgwt.extraJvmArgs="-Xmx768m -Xss1024k"

# ==========================================
# Stage 2: Production Runtime (Tomcat 10.1)
# ==========================================
FROM tomcat:10.1-jdk17-temurin

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Add MySQL Connector/J driver to Tomcat's common library directory
ADD https://repo1.maven.org/maven2/com/mysql/mysql-connector-j/8.3.0/mysql-connector-j-8.3.0.jar /usr/local/tomcat/lib/

# Remove default Tomcat webapps to keep it clean
RUN rm -rf /usr/local/tomcat/webapps/ROOT /usr/local/tomcat/webapps/examples /usr/local/tomcat/webapps/docs

# Copy the compiled WAR as ROOT application
COPY --from=builder /app/target/UniTime.war /usr/local/tomcat/webapps/ROOT.war

# Create and set permissions for UniTime data directory
RUN mkdir -p /usr/local/tomcat/data && chmod -R 777 /usr/local/tomcat/data

# Configure Tomcat setenv.sh for clean JVM parameter passing
RUN printf '%s\n' \
    'JVM_MEM="${JVM_MEM:--Xms512m -Xmx2048m}"' \
    'CONN_URL="${CONNECTION_URL:-jdbc:mysql://unitime-db:3306/timetable?useSSL=false&allowPublicKeyRetrieval=true&autoReconnect=true&characterEncoding=UTF-8}"' \
    'DB_USER="${CONNECTION_USERNAME:-timetable}"' \
    'DB_PASS="${CONNECTION_PASSWORD:-unitime}"' \
    'DATA_DIR="${UNITIME_DATA_DIR:-/usr/local/tomcat/data}"' \
    'if [ -z "$CATALINA_OPTS" ]; then' \
    '  export CATALINA_OPTS="$JVM_MEM -Dconnection.url=\"$CONN_URL\" -Dconnection.username=$DB_USER -Dconnection.password=$DB_PASS -Dunitime.data.dir=$DATA_DIR"' \
    'fi' \
    > /usr/local/tomcat/bin/setenv.sh && chmod +x /usr/local/tomcat/bin/setenv.sh

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
  CMD curl -f http://localhost:8080/ || exit 1

CMD ["catalina.sh", "run"]
