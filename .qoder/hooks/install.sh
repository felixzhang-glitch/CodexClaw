#!/usr/bin/env bash
# 把 .qoder/hooks/pre-push 挂载到 .git/hooks/pre-push（薄封装转发）。
#
# 特性：
#   - 不修改任何 git config（不设置 core.hooksPath）
#   - 不触碰已有的 .git/hooks/post-commit（Qoder AI tracker）
#   - 已存在非本工具生成的 pre-push 时先备份
#
# 用法：
#   bash .qoder/hooks/install.sh              安装
#   bash .qoder/hooks/install.sh --uninstall  卸载（存在备份则还原）

set -euo pipefail

MARKER="# BEGIN codeClaw secret-scan pre-push"
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$HOOK_DIR" rev-parse --show-toplevel)"
GIT_DIR="$(git -C "$HOOK_DIR" rev-parse --git-dir)"
case "$GIT_DIR" in
  /*) ;;
  *) GIT_DIR="$REPO_ROOT/$GIT_DIR" ;;
esac
TARGET="$GIT_DIR/hooks/pre-push"
REL_HOOK="${HOOK_DIR#"$REPO_ROOT"/}"

is_ours() {
  [ -f "$TARGET" ] && grep -qF "$MARKER" "$TARGET"
}

if [ "${1:-}" = "--uninstall" ]; then
  if ! is_ours; then
    echo "[install] $TARGET 不是本工具生成，未做任何改动"
    exit 0
  fi
  rm -f "$TARGET"
  latest_backup="$(ls -1t "$GIT_DIR/hooks/pre-push.bak."* 2>/dev/null | head -1 || true)"
  if [ -n "$latest_backup" ]; then
    mv "$latest_backup" "$TARGET"
    echo "[install] 已卸载并还原备份：$latest_backup -> $TARGET"
  else
    echo "[install] 已卸载 $TARGET"
  fi
  exit 0
fi

if [ -f "$TARGET" ] && ! is_ours; then
  backup="$TARGET.bak.$(date +%Y%m%d%H%M%S)"
  cp "$TARGET" "$backup"
  echo "[install] 已备份原有钩子：$backup"
fi

mkdir -p "$GIT_DIR/hooks"
cat > "$TARGET" <<EOF
#!/usr/bin/env bash
$MARKER
# 转发到版本化的钩子实现，便于随仓库分发与升级。
repo_root="\$(git rev-parse --show-toplevel)"
exec "\$repo_root/$REL_HOOK/pre-push" "\$@"
# END codeClaw secret-scan pre-push
EOF

chmod +x "$TARGET"
chmod +x "$HOOK_DIR/pre-push" "$HOOK_DIR/secret_scan.py"

echo "[install] 已挂载 pre-push 密钥扫描钩子：$TARGET -> $REL_HOOK/pre-push"
echo "[install] core.hooksPath 未被修改（当前值：$(git -C "$REPO_ROOT" config --get core.hooksPath || echo '<未设置>')）"
echo "[install] 自查全量文件：python3 $REL_HOOK/secret_scan.py --all"
