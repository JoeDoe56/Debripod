  function humanBytes(bytes){
    const v = Number(bytes || 0);
    if(!isFinite(v) || v <= 0) return "0 B";
    const units = ["B","KB","MB","GB","TB"];
    let n = v;
    let i = 0;
    while(n >= 1024 && i < units.length - 1){
      n /= 1024;
      i += 1;
    }
    const p = n >= 100 ? 0 : (n >= 10 ? 1 : 2);
    return n.toFixed(p) + " " + units[i];
  }
