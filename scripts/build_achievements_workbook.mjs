import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = path.resolve("D:/Code/doors-wiki");
const source = JSON.parse(
  await fs.readFile(path.join(root, "data", "achievements_current.json"), "utf8"),
);
const outputDir = path.join(root, "outputs", "achievements-2026-09-14");
const outputPath = path.join(outputDir, "DOORS_中文维基_成就文本.xlsx");

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("成就文本");
const info = workbook.worksheets.add("同步说明");

const headers = [
  "同步键",
  "分类",
  "成就名",
  "描述",
  "达成条件",
  "攻略",
  "参考资料",
  "奖励",
  "Secret",
  "Hidden",
  "Obtainable",
  "Badge ID",
  "旧版本",
  "Wiki 修订",
  "行哈希",
  "同步状态",
];

const rows = source.rows.map((row) => [
  row.key,
  row.category,
  row.title,
  row.text,
  row.directions,
  row.tutorial,
  row.references,
  row.rewards,
  row.secret,
  row.hidden,
  row.obtainable,
  row.badge_id,
  row.old_versions,
  row.wiki_rev,
  row.row_hash,
  row.sync_status,
]);

sheet.getRange(`A1:P${rows.length + 1}`).values = [headers, ...rows];
const table = sheet.tables.add(`A1:P${rows.length + 1}`, true, "AchievementsTable");
table.style = "TableStyleMedium2";
table.showBandedRows = true;
table.showFilterButton = true;

sheet.getRange(`A2:A${rows.length + 1}`).format.fill = "#E9E9E9";
sheet.getRange(`D2:F${rows.length + 1}`).format.fill = "#FFF6D8";
sheet.getRange(`P2:P${rows.length + 1}`).format.fill = "#E8F3E5";
sheet.getRange(`D2:F${rows.length + 1}`).format.wrapText = true;
sheet.getRange(`G2:G${rows.length + 1}`).format.wrapText = true;
sheet.getRange(`M2:M${rows.length + 1}`).format.wrapText = true;

const widths = [22, 14, 30, 46, 40, 60, 55, 30, 10, 10, 12, 22, 55, 12, 44, 14];
widths.forEach((width, index) => {
  sheet.getRangeByIndexes(0, index, rows.length + 1, 1).format.columnWidth = width;
});
sheet.getRange(`A2:P${rows.length + 1}`).format.rowHeight = 42;
sheet.freezePanes.freezeRows(1);
sheet.freezePanes.freezeColumns(3);
sheet.showGridLines = false;
sheet.tabColor = "#B9935A";

["A", "G", "H", "I", "J", "K", "L", "M", "N", "O"].forEach((column) => {
  const columnRange = sheet.getRange(`${column}:${column}`);
  columnRange.hidden = true;
});

info.getRange("A1:B2").values = [
  ["项目", "值"],
  ["数据源", "zh.doorsgame.wiki"],
];
info.getRange("A3:B11").values = [
  ["页面", "Module:BadgeData"],
  ["修订号", source.revision],
  ["成就数量", source.count],
  ["可编辑列", "描述、达成条件、攻略"],
  ["同步键", "必须保留；它用于识别对应的 Wiki 成就"],
  ["Wiki 更新", "机器人更新 Wiki 后，会自动刷新本表对应行"],
  ["腾讯文档更新", "检测到描述、条件或攻略变化后，自动回写 Wiki"],
  ["冲突", "两端同时变化时标记为“冲突”，不会自动覆盖"],
  ["生成时间", "2026-09-14"],
];
info.getRange("A1:B1").format = {
  fill: "#31435A",
  font: { bold: true, color: "#FFFFFF" },
};
info.getRange("A1:B11").format.borders = {
  preset: "all",
  style: "thin",
  color: "#D8D8D8",
};
info.getRange("A1:B11").format.font = { name: "Arial", size: 10 };
info.getRange("A1:B11").format.verticalAlignment = "center";
info.getRange("A2:B11").format.wrapText = true;
info.getRange("A2:B2").format.fill = "#FFF6D8";
info.getRange("A6:B6").format.fill = "#FFF6D8";
info.getRange("A7:B7").format.fill = "#E8F3E5";
info.getRange("A8:B8").format.fill = "#E8F3E5";
info.getRange("A9:B9").format.fill = "#FCE8E6";
info.getRange("A1:A11").format.columnWidth = 22;
info.getRange("B1:B11").format.columnWidth = 78;
info.showGridLines = false;
info.tabColor = "#5E6B7A";

workbook.recalculate();
await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(outputPath);
