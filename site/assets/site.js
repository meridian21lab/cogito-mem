// The install page starts on the visitor's system; its picker works without this.
const system = /Windows/.test(navigator.userAgent) ? "win" : /Linux/.test(navigator.userAgent) && !/Android/.test(navigator.userAgent) ? "linux" : null;
const pick = system && document.getElementById("os-" + system);
if (pick) pick.checked = true;

// Copy buttons for every command block.
document.querySelectorAll(".cmd").forEach((block) => {
  const code = block.querySelector("code");
  if (!code) return;
  const button = document.createElement("button");
  button.className = "copy";
  button.type = "button";
  button.textContent = "Copy";
  button.setAttribute("aria-label", "Copy the command");
  button.addEventListener("click", async () => {
    // comment lines (shown dim) are not part of the command
    const text = [...code.childNodes]
      .filter((n) => !(n.classList && n.classList.contains("dim")))
      .map((n) => n.textContent)
      .join("")
      .trim();
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      document.body.append(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    button.textContent = "Copied ✓";
    button.classList.add("done");
    setTimeout(() => {
      button.textContent = "Copy";
      button.classList.remove("done");
    }, 1600);
  });
  block.append(button);
});
