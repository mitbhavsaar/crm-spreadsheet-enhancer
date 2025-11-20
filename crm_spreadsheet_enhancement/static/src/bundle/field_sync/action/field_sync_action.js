/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { range } from "@web/core/utils/numbers";
import { WarningDialog } from "@web/core/errors/error_dialogs";
import { AbstractSpreadsheetAction } from "@spreadsheet_edition/bundle/actions/abstract_spreadsheet_action";
import { useSubEnv } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useSpreadsheetFieldSyncExtension } from "../field_sync_extension_hook";

export class SpreadsheetFieldSyncAction extends AbstractSpreadsheetAction {
    static template = "crm_customisation.CrmLeadSpreadsheetAction";
    static path = "crm-lead-spreadsheet";
    resModel = "crm.lead.spreadsheet";

    setup() {
        super.setup();
        
        this.dialogService = useService("dialog");
        this.notificationService = useService("notification");
        this.orm = useService("orm");
        
        this.notificationMessage = _t("Calculator ready");
        useSubEnv({ makeCopy: this.makeCopy.bind(this) });
        useSpreadsheetFieldSyncExtension();
        
        // Detect spreadsheet type
        this.spreadsheetType = null; // Will be 'crm' or 'sale'
        this.leadId = null;
        this.saleOrderId = null;
        this.spreadsheetId = null;
    }

    /**
     * Get main lists from spreadsheet data
     */
    getMainLists() {
        if (!this.spreadsheetData || !this.spreadsheetData.lists) {
            return [];
        }

        const lists = [];
        const listData = this.spreadsheetData.lists;

        // Convert lists object to array
        for (const [listId, listConfig] of Object.entries(listData)) {
            lists.push({
                id: listId,
                model: listConfig.model,
                domain: listConfig.domain,
                columns: listConfig.columns,
                sheetId: listConfig.sheetId,
                name: listConfig.name,
                context: listConfig.context || {},
                orderBy: listConfig.orderBy || [],
            });
        }

        return lists;
    }

    async writeToParent() {
        try {
            const activeSheetId = this.model.getters.getActiveSheetId();
            const { commands, errors } = await this.model.getters.getFieldSyncX2ManyCommands();

            if (errors.length) {
                this.dialogService.add(WarningDialog, {
                    title: _t("Unable to Save"),
                    message: errors.join("\n\n"),
                });
                return;
            }

            // Process commands based on spreadsheet type
            if (this.spreadsheetType === 'crm' && this.leadId) {
                await this.orm.write("crm.lead", [this.leadId], {
                    material_line_ids: commands,
                });
                
            } else if (this.spreadsheetType === 'sale' && this.saleOrderId) {
                await this.orm.write("sale.order", [this.saleOrderId], {
                    order_line: commands,
                });
            } else {
                throw new Error("No valid parent record found for saving");
            }
       
            this.notificationService.add(_t("Successfully saved changes from current sheet"), {
                type: "success",
            });
            
            this.env.config.historyBack();
            
        } catch (error) {
            this.dialogService.add(WarningDialog, {
                title: _t("Save Error"),
                message: _t("Failed to save changes: %s", error.message),
            });
        }
    }

    // Better initialization with backend data
    _initializeWith(data) {
        super._initializeWith(data);
        
        // CRM-specific data
        if (data.lead_id) {
            this.leadId = data.lead_id;
            this.spreadsheetType = 'crm';
        }
        
        // Sales-specific data
        if (data.sale_order_id) {
            this.saleOrderId = data.sale_order_id;
            this.spreadsheetType = 'sale';
        }
        
        // Store display names for UI
        if (data.lead_display_name) {
            this.leadDisplayName = data.lead_display_name;
        }
        if (data.order_display_name) {
            this.orderDisplayName = data.order_display_name;
        }
        
        this.spreadsheetId = data.sheet_id;

        // Store the raw data for later use
        this.backendData = data;
    }
    
    /**
     * Get appropriate button label based on type
     */
    get saveButtonLabel() {
        if (this.spreadsheetType === 'crm' && this.leadId) {
            const leadName = this.leadDisplayName || this.backendData?.lead_display_name || 'Lead';
            return _t("Save in %s", leadName);
        } else if (this.spreadsheetType === 'sale' && this.saleOrderId) {
            const orderName = this.orderDisplayName || this.backendData?.order_display_name || 'Order';
            return _t("Save in %s", orderName);
        }
        return _t("Save");
    }

    /**
     * Override to handle both CRM and Sales models
     */
    get resModel() {
        if (this.spreadsheetType === 'crm') {
            return "crm.lead.spreadsheet";
        } else if (this.spreadsheetType === 'sale') {
            return "sale.order.spreadsheet";
        }
        return "crm.lead.spreadsheet"; // default
    }

    /**
     * Get current record ID based on type
     */
    get currentRecordId() {
        if (this.spreadsheetType === 'crm') {
            return this.leadId;
        } else if (this.spreadsheetType === 'sale') {
            return this.saleOrderId;
        }
        return null;
    }

    /**
     * Enhanced error handling for spreadsheet loading
     */
    async loadSpreadsheet() {
        try {
            await super.loadSpreadsheet();
        } catch (error) {
            this.dialogService.add(WarningDialog, {
                title: _t("Load Error"),
                message: _t("Failed to load spreadsheet: %s", error.message),
            });
        }
    }
}

// Register custom spreadsheet actions
registry.category("actions").add("action_crm_lead_spreadsheet", SpreadsheetFieldSyncAction, { force: true });
registry.category("actions").add("action_sale_order_spreadsheet", SpreadsheetFieldSyncAction, { force: true });