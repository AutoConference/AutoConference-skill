"""Local, read-only view of the extension catalogue and actual run records."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from adapters.common import read_json, safe_input, safe_output


def _segmentation_previews(workspace, records):
    """Only current, hash-matched files from actual successful SAM runs."""
    result = {}
    for record in records:
        if record.get("request", {}).get("id") != "sam2" or record.get("status") != "completed":
            continue
        candidates = []
        source = record["request"].get("inputs", {}).get("image")
        if source:
            candidates.append((source, "原图", record.get("input_sha256", {}).get(source)))
        masks = [p for p in record.get("result", {}).get("artifacts", [])
                 if isinstance(p, str) and Path(p).suffix.lower() in (".png", ".jpg", ".jpeg")][:3]
        for index, path in enumerate(masks):
            candidates.append((path, f"分割掩膜 {index + 1}", record.get("artifact_sha256", {}).get(path)))
        previews = []
        for relative, caption, expected_hash in candidates:
            if not expected_hash or not isinstance(relative, str) or Path(relative).suffix.lower() not in (".png", ".jpg", ".jpeg"):
                continue
            try:
                path = safe_input(workspace, relative)
                if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
                    continue
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                if digest.hexdigest() == expected_hash:
                    previews.append({"path": relative, "caption": caption})
            except (OSError, ValueError):
                continue
        if previews and isinstance(record.get("run_id"), str):
            result[record["run_id"]] = previews
    return result


def build_report(workspace, catalog, config, records, domains) -> Path:
    workspace = Path(workspace).resolve(strict=True)
    replay = None
    preflight = []
    messages = []
    for relative, kind in (("refine-logs/EXTENSION_REPLAY.json", "replay"),
                           ("refine-logs/EXTENSION_PREFLIGHT.json", "preflight")):
        if (workspace / relative).exists():
            try:
                value = read_json(workspace, relative)
                if kind == "replay":
                    replay = value
                elif isinstance(value, list):
                    preflight = value
            except (OSError, ValueError) as error:
                messages.append(f"{relative}: {error}")
    payload = {
        "domains": domains, "extensions": list(catalog.values()),
        "levels": config["extensions"], "records": records,
        "replay": replay, "preflight": preflight, "messages": messages,
        "segmentation_previews": _segmentation_previews(workspace, records),
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    # The script block must remain inert even if a recorded purpose/error contains
    # an HTML closing tag. All UI text is assigned with textContent, never innerHTML.
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    page = PAGE.replace("__REPORT_DATA__", encoded)
    path = safe_output(workspace, "refine-logs/science-extensions.html")
    path.write_text(page, encoding="utf-8")
    return path


PAGE = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>科研扩展 · AutoConference</title>
<style>
:root{color-scheme:light;--paper:#f5f2eb;--card:#fffdf9;--ink:#342d26;--muted:#7b7165;--line:#e3dbcf;--brown:#785b3e;--pale:#eae0d1;--green:#4b6851;--red:#9b4a3d;--amber:#8a672f}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}button,select{font:inherit}button,select,a,summary{outline-offset:4px}a{color:var(--brown);text-underline-offset:3px}main{max-width:1344px;margin:auto;padding:36px 44px 56px}.masthead{display:flex;justify-content:space-between;gap:20px;align-items:center;padding-bottom:25px;border-bottom:1px solid var(--line)}.brand{font:600 24px/1.2 Georgia,serif;letter-spacing:-.6px}.local{color:var(--muted);font-size:13px}.intro{display:flex;justify-content:space-between;align-items:end;gap:24px;margin:34px 0 26px}h1{font-size:36px;line-height:1.3;letter-spacing:-1px;margin:0 0 10px}p{margin:0}.intro p{color:var(--muted)}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:25px}.stat{padding:18px 20px;background:#eee8de;border-radius:12px}.stat strong{display:block;font-size:28px;line-height:1.3;font-weight:650}.stat span{color:var(--muted);font-size:13px}.toolbar{display:flex;justify-content:space-between;align-items:center;gap:18px;margin:22px 0}.level-control{display:flex;align-items:center;gap:14px;flex-wrap:wrap}.level-label{font-size:14px;font-weight:600}.segmented{display:flex;background:#e9e2d7;border:1px solid var(--line);border-radius:10px;padding:3px;gap:3px}.segmented button{border:0;background:transparent;color:var(--muted);padding:7px 14px;border-radius:7px;cursor:pointer;font-size:13px}.segmented button.active{background:var(--card);color:var(--ink);box-shadow:0 1px 3px #342d2610}.toolbar-note{font-size:12px;color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.card{min-width:0;background:var(--card);border:1px solid var(--line);border-radius:15px;padding:24px;display:flex;flex-direction:column}.card-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:17px}.domain{font-size:13px;font-weight:600;color:var(--brown)}.owner-level{font-size:12px;color:var(--muted);white-space:nowrap}.tool-name{font-size:23px;line-height:1.3;margin:0 0 7px;font-weight:650;letter-spacing:-.4px}.summary{color:var(--muted);font-size:14px;min-height:45px;margin-bottom:17px}.scope{background:#f3eee6;border-left:3px solid #b69a77;border-radius:0 7px 7px 0;padding:11px 13px;font-size:13px;min-height:64px}.scope strong{font-weight:650;display:block;margin-bottom:3px}.scope p{color:#655747}.result-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:18px 0 12px}.status{display:inline-flex;align-items:center;gap:7px;font-size:13px;font-weight:600}.status:before{content:"";height:7px;width:7px;border-radius:50%;background:currentColor}.ok{color:var(--green)}.warn{color:var(--amber)}.bad{color:var(--red)}.neutral{color:var(--muted)}.duration{font-size:12px;color:var(--muted)}.metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 14px;margin:0 0 12px}.metric{min-width:0;padding:9px 0;border-top:1px solid #eee7de}.metric dt{font-size:11px;line-height:1.4;color:var(--muted);overflow-wrap:anywhere}.metric dd{margin:4px 0 0;font-size:18px;line-height:1.3;font-variant-numeric:tabular-nums;font-weight:550}.empty,.reason{font-size:13px;color:var(--muted);padding:7px 0 14px;overflow-wrap:anywhere}.reason{color:var(--red)}.replay{font-size:12px;color:var(--muted);margin-bottom:14px}.replay.good{color:var(--green)}.card-foot{margin-top:auto;padding-top:13px;border-top:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:12px}.record-count{color:var(--muted)}details{margin-top:12px;font-size:13px}summary{cursor:pointer;color:var(--brown);padding:5px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f0ece5;border-radius:7px;padding:13px;max-height:340px;overflow:auto;font:11px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace}.limits{margin:8px 0;padding-left:20px;color:var(--muted);font-size:12px}.limits li{margin:6px 0}.footer{border-top:1px solid var(--line);margin-top:30px;padding-top:18px;color:var(--muted);font-size:12px;display:flex;justify-content:space-between;gap:20px}.message{padding:12px 16px;background:#fff3df;color:var(--amber);border-radius:8px;margin-bottom:16px;font-size:13px}.hidden{display:none!important}@media(min-width:1550px){main{max-width:1500px}.grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:720px){main{padding:22px 17px 34px}.brand{font-size:21px}.local{font-size:11px}.intro{margin-top:26px}h1{font-size:30px}.stats{gap:8px}.stat{padding:12px 10px}.stat strong{font-size:24px}.stat span{font-size:11px}.toolbar{align-items:flex-start;flex-direction:column;gap:8px}.level-control{gap:8px}.segmented button{padding:7px 10px}.grid{grid-template-columns:1fr;gap:14px}.card{padding:20px}.summary{min-height:0}.footer{flex-direction:column;gap:7px}.scope{min-height:0}.tool-name{font-size:22px}}
</style>
<style>
.segmentation-gallery{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:10px}.segmentation-gallery figure{margin:0;min-width:0}.segmentation-gallery img{display:block;width:100%;height:auto;max-height:230px;object-fit:contain;background:#ebe7e0;border:1px solid var(--line);border-radius:7px}.segmentation-gallery figcaption{font-size:12px;color:var(--muted);margin-top:5px}.segmentation-note{font-size:12px;color:var(--muted);margin-top:8px}@media(max-width:380px){.segmentation-gallery{grid-template-columns:1fr}}
</style>
</head>
<body><main>
<header class="masthead"><div class="brand">AutoConference</div><div class="local">本地工具包 · 运行报告</div></header>
<section class="intro"><div><h1>科研扩展</h1><p>按研究任务调用工具，保留每一步的运行记录。</p></div></section>
<div class="stats" id="stats"></div>
<div id="messages"></div>
<div class="toolbar"><div class="level-control"><span class="level-label">查看档位</span><div class="segmented" id="levels" aria-label="查看扩展档位"></div></div><p class="toolbar-note">切换仅用于查看，不会更改配置或运行工具。</p></div>
<section class="grid" id="grid" aria-label="研究领域与扩展"></section>
<footer class="footer"><p>运行成功表示工具已完成所选子任务；研究收益需要用真实任务和对照实验验证。</p><p id="generated"></p></footer>
</main>
<script type="application/json" id="report-data">__REPORT_DATA__</script>
<script>
"use strict";
const D=JSON.parse(document.getElementById("report-data").textContent);
const $=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=String(text);return e};
const levels=[0,25,75,100], tierNames={0:"关闭",25:"辅助检查",75:"主要模块",100:"完整子任务"};
const statusNames={completed:"运行成功",disabled:"关闭 · 未调用",unavailable:"依赖未就绪",timeout:"运行超时",error:"运行失败",failed:"检查未通过"};
const statusClass={completed:"ok",disabled:"neutral",unavailable:"warn",timeout:"warn",error:"bad",failed:"bad"};
const metricNames={observations:"已观测实验",dimensions:"参数维度",best_observed:"最佳观测值",checked_candidates:"已检查候选点",mean_posterior_std:"平均预测不确定性",log_expected_improvement:"对数期望改进",candidate_predicted_mean:"候选点预测值",holdout_rmse:"留出集 RMSE",transitions:"轨迹步数",episode_ends:"回合边界",terminal_ends:"终止边界",truncated_ends:"截断边界",reward_sum:"奖励合计",advantage_mean:"平均优势估计",sample_size:"小批量样本数",accuracy:"准确率",samples:"样本数",records:"记录数",windows:"窗口数",atoms:"原子数",steps:"模拟步数",num_samples:"样本数",holdout_points:"独立检查点"};
Object.assign(metricNames, {
  candidate_predicted_std:"候选点预测标准差",advantage_std:"优势估计标准差",
  boundary_audit_max_error:"独立核对最大误差",boundary_audit_tolerance:"核对误差容限",
  replay_roundtrip_error:"轨迹读取误差",value_target_mean:"平均价值目标",
  examples:"评测样本",choice_accuracy:"选项准确率",generation_exact_match:"生成答案匹配率",
  mean_target_loglikelihood:"平均目标对数似然",baseline_accuracy:"基线准确率",
  exact_accuracy:"答案匹配率",paired_accuracy_difference:"与基线的准确率差",
  paired_wins:"优于基线的样本",paired_losses:"低于基线的样本",worst_group_accuracy:"最低分组准确率",
  total_cost:"记录费用合计",total_tokens:"记录 Token 合计",masks:"分割掩膜",
  mean_predicted_iou:"模型估计 IoU",image_width:"图像宽度（像素）",image_height:"图像高度（像素）",
  total_mask_area_pixels:"掩膜面积合计（像素）",records_processed:"已处理记录",
  splits_present:"保留的数据划分",flat_channels:"平坦通道",independent_record_normalization:"逐记录独立标准化",
  standardized_mean:"标准化均值",standardized_std:"标准化标准差",values_processed:"已处理数值",
  trailing_samples_dropped:"窗口尾部舍弃样本",duration:"求解时间范围",equations:"方程数",
  evaluation_points:"检查点数",training_iterations:"训练步数",final_training_loss:"最终训练损失",
  reference_rmse:"参考解 RMSE",heldout_reference_rmse:"独立检查点 RMSE",
  heldout_residual_rms:"独立方程残差 RMS",initial_condition_max_error:"初值最大误差",
  particles:"粒子数",simulated_time_ps:"模拟时长（ps）",frames:"轨迹帧数",
  max_energy_drift_kj_mol:"最大能量漂移（kJ/mol）",
  half_step_endpoint_rms_difference_nm:"减半步长终点差（nm）",
  endpoint_displacement_rms_nm:"终点位移 RMS（nm）",final_potential_kj_mol:"最终势能（kJ/mol）",
  initial_potential_kj_mol:"初始势能（kJ/mol）",initial_max_force_kj_mol_nm:"初始最大力（kJ/mol/nm）",
  initial_energy_absolute_error_kj_mol:"初始能量误差（kJ/mol）",
  max_momentum_drift_dalton_nm_ps:"最大动量漂移（Da·nm/ps）"
});
const primaryMetrics={
  botorch:["observations","candidate_predicted_mean","holdout_rmse","best_observed","checked_candidates","mean_posterior_std"],
  torchrl:["transitions","episode_ends","advantage_mean","boundary_audit_max_error"],
  lm_eval:["examples","choice_accuracy","generation_exact_match","mean_target_loglikelihood"],
  inspect_ai:["records","exact_accuracy","baseline_accuracy","paired_accuracy_difference"],
  sam2:["masks","mean_predicted_iou","image_width","image_height"],
  braindecode:["records_processed","windows","splits_present","flat_channels"],
  deepxde:["training_iterations","reference_rmse","heldout_residual_rms","initial_condition_max_error"],
  openmm:["particles","simulated_time_ps","max_energy_drift_kj_mol","half_step_endpoint_rms_difference_nm"]
};
const toolIds=new Set(D.extensions.map(t=>t.id));
const records=D.records.filter(r=>r&&r.request&&toolIds.has(r.request.id));
const preflight=new Map((D.preflight||[]).map(r=>[r.id,r]));
const replayEntries=Array.isArray(D.replay)?D.replay:D.replay&&Array.isArray(D.replay.results)?D.replay.results:D.replay?[D.replay]:[];
const replayByRun=new Map(replayEntries.filter(r=>r&&r.run_id).map(r=>[r.run_id,r]));
const replayIds=new Set(replayEntries.filter(r=>r&&r.replay_id).map(r=>r.replay_id));
const isReplay=r=>Boolean(r.replay_of)||replayIds.has(r.run_id);
const ordinary=records.filter(r=>!isReplay(r));
const successful=new Set(ordinary.filter(r=>r.status==="completed").map(r=>r.request.id));
let selected="latest";
const counts=[[Object.keys(D.domains).length,"研究类别"],[Object.values(D.levels).filter(v=>v>0).length,"已开启扩展"],[successful.size,"有成功运行"],[D.extensions.filter(x=>!successful.has(x.id)).length,"尚未跑通"]];
for(const [number,label] of counts){const box=$("div","stat");box.append($("strong","",number),$("span","",label));document.getElementById("stats").append(box)}
for(const message of D.messages||[])document.getElementById("messages").append($("p","message",message));
function numeric(value){if(!Number.isFinite(value))return String(value);if(Number.isInteger(value))return value.toLocaleString("en-US");if(value!==0&&(Math.abs(value)<.0001||Math.abs(value)>=1e6))return value.toExponential(3);return String(Number(value.toPrecision(6)))}
function external(url,label){try{const parsed=new URL(url);if(parsed.protocol!=="https:"||parsed.username||parsed.password)return $("span","",label);const a=$("a","",label);a.href=parsed.href;a.target="_blank";a.rel="noopener noreferrer";return a}catch{return $("span","",label)}}
function latestRun(list){return [...list].sort((a,b)=>String(a.started_at||a.run_id||"").localeCompare(String(b.started_at||b.run_id||""))).at(-1)}
function summaryDetails(label,value){const details=$("details");details.append($("summary","",label),$("pre","",JSON.stringify(value,null,2)));return details}
function localImagePath(value){
  if(typeof value!=="string"||!value||value.startsWith("/")||value.includes("\\")||value.includes(":")||/[\x00-\x1f]/.test(value)||! /\.(png|jpe?g)$/i.test(value))return null;
  const parts=value.split("/");if(parts.some(p=>!p||p==="."||p===".."))return null;
  return "../"+parts.map(encodeURIComponent).join("/");
}
function segmentationDetails(record){
  const images=(D.segmentation_previews||{})[record.run_id]||[];
  const section=$("details");section.append($("summary","","分割结果"));
  const gallery=$("div","segmentation-gallery");
  for(const item of images){const src=localImagePath(item.path);if(!src)continue;const figure=$("figure");const img=$("img");img.src=src;img.alt=item.caption;img.loading="lazy";img.decoding="async";figure.append(img,$("figcaption","",item.caption));gallery.append(figure)}
  if(!gallery.childElementCount)return null;
  section.append(gallery,$("p","segmentation-note","原图与本次运行实际输出的掩膜；最多显示前三张。"));return section;
}
function render(){
  document.querySelectorAll("#levels button").forEach(b=>{const active=String(selected)===b.dataset.level;b.classList.toggle("active",active);b.setAttribute("aria-pressed",String(active))});
  const grid=document.getElementById("grid");grid.replaceChildren();
  for(const [domain,label] of Object.entries(D.domains)){
    const tools=D.extensions.filter(t=>t.domain===domain);
    if(!tools.length){const card=$("article","card");card.append($("div","domain",label),$("h2","tool-name","暂无扩展"),$("p","empty","该类别尚未加入可执行适配器。"));grid.append(card);continue}
    for(const tool of tools){
      const history=ordinary.filter(r=>r.request.id===tool.id);
      const replays=records.filter(r=>r.request.id===tool.id&&isReplay(r));
      const latest=latestRun(history);
      const tier=selected==="latest"?(latest?latest.request.tier:(D.levels[tool.id]||0)):Number(selected);
      const record=latestRun(history.filter(r=>r.request.tier===tier));
      const card=$("article","card");card.dataset.extension=tool.id;
      const head=$("div","card-head");head.append($("div","domain",label),$("div","owner-level","配置上限 "+(D.levels[tool.id]||0)));
      card.append(head,$("h2","tool-name",tool.name),$("p","summary",tool.summary.zh||tool.summary.en));
      const scope=$("div","scope");scope.append($("strong","",tier+" · "+tierNames[tier]));
      const tierDescription=tier===0?"保留原有科研流程，不调用此扩展。":tool.tiers[String(tier)];
      scope.append($("p","",typeof tierDescription==="string"?tierDescription:tierDescription.zh||tierDescription.en));card.append(scope);
      const resultHead=$("div","result-head");
      if(record){
        resultHead.append($("span","status "+(statusClass[record.status]||"neutral"),statusNames[record.status]||record.status));
        if(Number.isFinite(record.duration_seconds))resultHead.append($("span","duration",numeric(record.duration_seconds)+" 秒"));
      }else resultHead.append($("span","status neutral","本档尚无运行记录"));
      card.append(resultHead);
      if(record&&record.status==="completed"){
        const values=record.result&&record.result.metrics||{};
        const metrics=[...new Set([...(primaryMetrics[tool.id]||[]),...Object.keys(values)])]
          .filter(name=>Object.hasOwn(values,name)).map(name=>[name,values[name]]);
        const dl=$("dl","metrics");
        for(const [name,value] of metrics.slice(0,4)){const row=$("div","metric");row.append($("dt","",metricNames[name]||name.replaceAll("_"," ")),$("dd","",numeric(value)));dl.append(row)}
        card.append(dl);
        const verification=replayByRun.get(record.run_id);
        card.append($("p","replay"+(verification&&verification.status==="passed"?" good":""),verification?(verification.status==="passed"?"复验通过 · 相同输入与版本":"复验未通过 · 查看记录了解原因"):"尚无该次运行的复验结论"));
      }else if(record&&record.reason)card.append($("p",record.status==="disabled"?"empty":"reason",record.reason));
      else if(!record){
        const environment=preflight.get(tool.id);
        card.append($("p","empty",environment&&environment.status==="unavailable"?"依赖未就绪；安装并检查环境后再运行。":"选择这个档位后，需要在本地运行工具才会产生结果。"));
      }
      const foot=$("div","card-foot");foot.append(external(tool.project_url,"项目与源码 ↗"),$("span","record-count",history.length+" 次运行"+(replays.length?" · "+replays.length+" 次复验":"")));card.append(foot);
      if(tool.id==="sam2"&&record&&record.status==="completed"){const segmentation=segmentationDetails(record);if(segmentation)card.append(segmentation)}
      if(record)card.append(summaryDetails("查看本次输入与结果",record));
      const verification=record&&replayByRun.get(record.run_id);
      if(verification)card.append(summaryDetails("查看复验记录",verification));
      if(history.length>1)card.append(summaryDetails("全部运行记录（"+history.length+"）",history));
      if(replays.length)card.append(summaryDetails("复验执行记录（"+replays.length+"）",replays));
      const instructions=$("details");instructions.append($("summary","","输入要求与适用范围"),$("p","empty",tool.input_description));
      const limits=$("ul","limits");for(const item of tool.limitations||[])limits.append($("li","",item));instructions.append(limits,external(tool.docs_url,"官方说明 ↗"));card.append(instructions);
      grid.append(card);
    }
  }
}
for(const value of ["latest",...levels]){const b=$("button","",value==="latest"?"各自最新":String(value));b.type="button";b.dataset.level=String(value);b.addEventListener("click",()=>{selected=value;render()});document.getElementById("levels").append(b)}
document.getElementById("generated").textContent="报告生成于 "+new Date(D.generated).toLocaleString("zh-CN",{hour12:false});
render();
</script></body></html>'''
