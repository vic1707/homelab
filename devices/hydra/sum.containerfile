# SUM 2.15.0
    FROM docker.io/library/debian:13.2 AS sum

    ARG TARGETARCH

    RUN apt-get update && \
        apt-get install --yes --no-install-recommends ca-certificates curl

    RUN set -eux; \
        case "$TARGETARCH" in \
            amd64) arch=x86_64; download_id=1026 ;; \
            arm64) arch=arm64; download_id=1020 ;; \
            *) echo "Unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
        esac; \
        base_url="https://www.supermicro.com/Bios/sw_download/${download_id}"; \
        curl --fail --location --silent --show-error \
            "${base_url}/checksum.txt" \
            --output /tmp/checksum.txt; \
        archive="$(sed -n '1s!.*/!!p' /tmp/checksum.txt)"; \
        checksum="$(sed -n '3s/^MD5 CheckSum: //p' /tmp/checksum.txt)"; \
        test -n "$archive"; \
        test -n "$checksum"; \
        curl --fail --location --silent --show-error \
            "${base_url}/${archive}" \
            --output /tmp/sum.tar.gz; \
        printf '%s  %s\n' "$checksum" /tmp/sum.tar.gz | md5sum --check --strict; \
        mkdir /out; \
        tar --extract --gzip --file /tmp/sum.tar.gz --directory /out \
            --strip-components=1 --wildcards "*/sum"; \
        chmod 0555 /out/sum

    COPY import-libs.sh /bin/import-libs.sh
    RUN /bin/import-libs.sh /out/sum

# FS
    FROM docker.io/library/alpine:3.23.0 AS fs

    RUN mkdir -p \
        /FS/bin \
        /FS/etc \
        /FS/lib \
        /FS/tmp && \
        printf 'nobody:x:65534:65534:nobody:/tmp:/sbin/nologin\n' > /FS/etc/passwd && \
        chmod 1777 /FS/tmp && \
        ln -s lib /FS/lib64

    COPY --from=sum /lib/dyn /FS/lib
    COPY --from=sum /out/sum /FS/bin/sum

# Final image
    FROM scratch

    USER 65534:65534

    COPY --from=fs /FS /

    WORKDIR /tmp

    RUN ["/bin/sum", "--version"]

    ENTRYPOINT ["/bin/sum"]
