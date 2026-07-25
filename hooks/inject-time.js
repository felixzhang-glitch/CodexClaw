// opencode plugin: 每条用户消息注入当前系统时间（fail-open，出错不影响对话）
export const InjectTime = async () => {
  return {
    "chat.message": async (input, output) => {
      try {
        const now = new Date();
        const pad = (n) => String(n).padStart(2, "0");
        const ts = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
        const weekday = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][now.getDay()];
        output.parts.push({
          id: `prt_time${now.getTime().toString(36)}`,
          sessionID: input.sessionID,
          messageID: output.message.id,
          type: "text",
          text: `<system-context>当前系统时间: ${ts} ${weekday}</system-context>`,
          synthetic: true,
        });
      } catch {
        // fail-open
      }
    },
  };
};
