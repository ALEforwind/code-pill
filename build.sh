#!/bin/bash
# 构建 .deb 安装包：./build.sh  →  dist/codepill_<version>_all.deb
set -euo pipefail

cd "$(dirname "$0")"
PROJECT_DIR="$PWD"
PKG_NAME="codepill"
VERSION="$(python3 -c 'import re,sys;print(re.search(r"__version__ = \"([^\"]+)\"", open("src/codepill/__init__.py", encoding="utf-8").read()).group(1))')"
BUILD_DIR="$PROJECT_DIR/build"
ROOT="$BUILD_DIR/${PKG_NAME}_${VERSION}"
DIST="$PROJECT_DIR/dist"
DEB="$DIST/${PKG_NAME}_${VERSION}_all.deb"

echo "==> 代码贴 CodePill $VERSION"

rm -rf "$BUILD_DIR"
mkdir -p "$ROOT" "$DIST"

# ---------------------------------------------------------------- 程序文件
install -d "$ROOT/usr/bin" "$ROOT/usr/lib/codepill"
install -m 755 packaging/deb/usr/bin/codepill "$ROOT/usr/bin/codepill"
cp -r src/codepill "$ROOT/usr/lib/codepill/"
find "$ROOT/usr/lib/codepill" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$ROOT/usr/lib/codepill" -name '*.pyc' -delete
find "$ROOT/usr/lib/codepill" -type f -exec chmod 644 {} +

# ---------------------------------------------------------------- 图标
echo "==> 生成图标"
python3 tools/make_icons.py \
    --svg src/codepill/assets/hicolor/scalable/apps/codepill.svg \
    --out "$ROOT/usr/share/icons/hicolor"
find "$ROOT/usr/share/icons" -type f -exec chmod 644 {} +

# ---------------------------------------------------------------- 桌面入口 / 自启动
install -d "$ROOT/usr/share/applications" "$ROOT/etc/xdg/autostart"
install -m 644 packaging/deb/usr/share/applications/codepill.desktop "$ROOT/usr/share/applications/codepill.desktop"
install -m 644 packaging/deb/etc/xdg/autostart/codepill.desktop "$ROOT/etc/xdg/autostart/codepill.desktop"

# ---------------------------------------------------------------- 文档
DOC="$ROOT/usr/share/doc/codepill"
install -d "$DOC/examples"
install -m 644 README.md "$DOC/README.md"
install -m 644 packaging/copyright "$DOC/copyright"
if [ -f LICENSE ]; then install -m 644 LICENSE "$DOC/LICENSE"; fi
install -m 644 examples/snippets.example.json "$DOC/examples/snippets.example.json"
if [ -d docs ]; then
    install -d "$DOC/docs"
    install -m 644 docs/*.png "$DOC/docs/"
fi
install -m 644 packaging/changelog "$DOC/changelog"
gzip -9n "$DOC/changelog"

# ---------------------------------------------------------------- DEBIAN 控制信息
install -d "$ROOT/DEBIAN"
cp packaging/deb/DEBIAN/postinst packaging/deb/DEBIAN/postrm "$ROOT/DEBIAN/"
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/postrm"

INSTALLED_SIZE="$(du -sk --exclude=DEBIAN "$ROOT" | cut -f1)"
sed -e "s/__VERSION__/${VERSION}/" -e "s/__SIZE__/${INSTALLED_SIZE}/" \
    packaging/deb/DEBIAN/control.in > "$ROOT/DEBIAN/control"
chmod 644 "$ROOT/DEBIAN/control"

# 统一权限：目录 755，脚本 755，其余 644
find "$ROOT" -type d -exec chmod 755 {} +
chmod 755 "$ROOT/usr/bin/codepill" "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/postrm"

# md5sums（dpkg 用来校验文件完整性）
(cd "$ROOT" && find usr etc -type f 2>/dev/null | sort | xargs -r md5sum) > "$ROOT/DEBIAN/md5sums"
chmod 644 "$ROOT/DEBIAN/md5sums"

# ---------------------------------------------------------------- 打包
echo "==> 打包 $DEB"
dpkg-deb --root-owner-group --build "$ROOT" "$DEB" >/dev/null
dpkg-deb --info "$DEB"
echo
echo "完成：$DEB ($(du -h "$DEB" | cut -f1))"
