FROM ghcr.io/jguer/yay-builder:latest AS sum

	ARG VERSION=2.13.0
	USER nobody:nobody
	
	WORKDIR /sum
	RUN git clone https://aur.archlinux.org/supermicro-update-manager.git .
	RUN git checkout "$(git log -S "pkgver = ${VERSION}" --format=%H -- .SRCINFO | tail -1)"

	RUN makepkg --noconfirm 

    COPY import-libs.sh /bin/import-libs.sh
	USER root
    RUN /bin/import-libs.sh /sum/pkg/supermicro-update-manager/usr/bin/supermicro-update-manager

# FS
    FROM docker.io/library/alpine:3.24.1 AS fs

    RUN mkdir -p \
        /FS/bin \
        /FS/etc \
        /FS/lib \
        /FS/tmp && \
        printf 'nobody:x:65534:65534:nobody:/tmp:/sbin/nologin\n' > /FS/etc/passwd && \
        chmod 1777 /FS/tmp && \
        ln -s lib /FS/lib64

    COPY --from=sum /lib/dyn /FS/lib
    COPY --from=sum /sum/pkg/supermicro-update-manager/usr/bin/supermicro-update-manager /FS/bin/sum

# Final image
    FROM scratch

    USER 65534:65534

    ENV LD_LIBRARY_PATH=/lib

    COPY --from=fs /FS /

    WORKDIR /tmp

    RUN ["/bin/sum", "--version"]

    ENTRYPOINT ["/bin/sum"]
