/** @odoo-module **/

import { addSpreadsheetActionLazyLoader } from "@spreadsheet/assets_backend/spreadsheet_action_loader";

// Register your CRM Spreadsheet Action
addSpreadsheetActionLazyLoader("action_crm_lead_spreadsheet", "crm-lead-spreadsheet");
