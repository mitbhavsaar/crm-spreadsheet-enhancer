/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import * as spreadsheet from "@odoo/o-spreadsheet";

console.log("🔧 [CRM Spreadsheet] Dropdown arrow patch loading...");

// Patch the Model to show dropdown arrows for data validation
patch(spreadsheet.Model.prototype, {
    /**
     * Override to determine if a cell should display a dropdown arrow icon
     * @param {Object} cellPosition - {col, row, sheetId}
     * @returns {boolean}
     */
    cellHasListDataValidationIcon(cellPosition) {
        try {
            // Get validation rule for this cell
            const rule = this.getters.getValidationRuleForCell?.(cellPosition);

            if (!rule || !rule.criterion) {
                return super.cellHasListDataValidationIcon?.(cellPosition) || false;
            }

            const criterion = rule.criterion;

            // Check if this is a list-type validation
            const isList =
                criterion.type === "isValueInList" ||
                criterion.type === "isValueInRange";

            // Check if arrow display is enabled
            const hasArrow = criterion.displayStyle === "arrow";

            if (isList && hasArrow) {
                console.log(
                    `⬇️ Dropdown arrow @ Sheet:${cellPosition.sheetId}, Row:${cellPosition.row}, Col:${cellPosition.col}`
                );
                return true;
            }
        } catch (err) {
            console.error("❌ Dropdown patch error:", err);
        }

        // Fallback to parent implementation
        return super.cellHasListDataValidationIcon?.(cellPosition) || false;
    },
});

console.log("✅ Dropdown arrow patch applied successfully");

