import { Component, onWillUnmount, useState } from "@odoo/owl";
import { components, helpers } from "@odoo/o-spreadsheet";
import { ModelFieldSelector } from "@web/core/model_field_selector/model_field_selector";
import { browser } from "@web/core/browser/browser";

const { Section, SelectionInput } = components;
const { positionToZone, deepEquals } = helpers;

export class FieldSyncSidePanel extends Component {
    static template = "crm_spreadsheet_enhancement.FieldSyncSidePanel";
    static components = { ModelFieldSelector, Section, SelectionInput };
    static props = {
        onCloseSidePanel: Function,
        position: Object,
        isNewlyCreate: { type: Boolean, optional: true },
    };
    static defaultProps = {
        isNewlyCreate: false,
    };

    setup() {
        this.state = useState({
            newPosition: undefined,
            updateSuccessful: false,
        });
        this.showSaved(this.props.isNewlyCreate);
        onWillUnmount(() => browser.clearTimeout(this.timeoutId));
    }

    /**
     * ✅ FIXED: Get current list with proper model detection
     */
    getCurrentList() {
        const fieldSync = this.fieldSync;
        if (!fieldSync) {
            console.warn("⚠️ No field sync found");
            return null;
        }

        const lists = this.env.model.getters.getMainLists();
        const currentList = lists.find(list => list.id === fieldSync.listId);

        if (!currentList) {
            console.error(`❌ List ${fieldSync.listId} not found in:`, lists);
            return null;
        }

        console.log(`✅ Current list: ${currentList.id}, model: ${currentList.model}`);
        return currentList;
    }

    /**
     * ✅ FIXED: Get current model name with validation
     */
    get currentModelName() {
        const list = this.getCurrentList();
        const modelName = list ? list.model : null;

        console.log(`🔍 Current model name: ${modelName}`);

        // ✅ Validate against supported models
        const supportedModels = this.env.model.getters.getSupportedModels();
        if (modelName && !supportedModels[modelName]) {
            console.error(`❌ Unsupported model: ${modelName}`);
            return null;
        }

        return modelName;
    }

    /**
     * ✅ FIXED: Get display name with fallback
     */
    get modelDisplayName() {
        const models = this.env.model.getters.getSupportedModels();
        const modelName = this.currentModelName;

        if (!modelName) {
            return 'Record';
        }

        const displayName = models[modelName]?.displayName || 'Record';
        console.log(`📝 Model display name: ${displayName} (from ${modelName})`);

        return displayName;
    }

    get fieldSyncPositionString() {
        const position = this.state.newPosition ?? this.props.position;
        const zone = positionToZone(position);
        const sheetId = position.sheetId;
        const range = this.env.model.getters.getRangeFromZone(sheetId, zone);
        return this.env.model.getters.getRangeString(range, sheetId);
    }

    get fieldSync() {
        return this.env.model.getters.getFieldSync(this.props.position);
    }

    /**
     * ✅ FIXED: Filter writable fields based on model
     */
    filterField(field) {
        const modelName = this.currentModelName;

        // Exclude parent fields based on model
        const excludeFields = [];
        if (modelName === 'crm.material.line') {
            excludeFields.push('lead_id');
            // 🔥 exclude 'price_custom' to avoid duplicate Price fields (keep standard 'price')
            excludeFields.push('price_custom');
        } else if (modelName === 'sale.order.line') {
            excludeFields.push('order_id');
        }

        const isValid = (
            !field.readonly &&
            !excludeFields.includes(field.name) &&
            ["integer", "float", "monetary", "char", "text", "many2one", "boolean"].includes(field.type)
        );

        if (isValid) {
            console.log(`✅ Field allowed: ${field.name} (${field.type})`);
        }

        return isValid;
    }

    updateRecordPosition(event) {
        this.updateFieldSync({ indexInList: parseInt(event.target.value) - 1 });
    }

    updateField(fieldName) {
        console.log(`🔄 Updating field to: ${fieldName}`);
        this.updateFieldSync({ fieldName });
    }

    onRangeChanged([rangeString]) {
        const range = this.env.model.getters.getRangeFromSheetXC(
            this.env.model.getters.getActiveSheetId(),
            rangeString
        );
        if (rangeString && !range.invalidXc) {
            this.state.newPosition ??= {};
            this.state.newPosition.sheetId = range.sheetId;
            this.state.newPosition.col = range.zone.left;
            this.state.newPosition.row = range.zone.top;
        }
    }

    onRangeConfirmed() {
        const newPosition = this.state.newPosition;
        if (!newPosition || deepEquals(newPosition, this.props.position)) {
            return;
        }
        this.updateFieldSync(newPosition);
        this.env.model.dispatch("DELETE_FIELD_SYNCS", {
            sheetId: this.props.position.sheetId,
            zone: positionToZone(this.props.position),
        });
        this.env.model.selection.selectCell(newPosition.col, newPosition.row);
        this.env.openSidePanel("FieldSyncSidePanel");
    }

    updateFieldSync(partialFieldSync) {
        const { sheetId, col, row } = this.props.position;
        const result = this.env.model.dispatch("ADD_FIELD_SYNC", {
            sheetId,
            col,
            row,
            listId: this.fieldSync.listId,
            ...this.fieldSync,
            ...partialFieldSync,
        });
        this.showSaved(result.isSuccessful);
    }

    showSaved(isDisplayed) {
        this.state.updateSuccessful = isDisplayed;
        browser.clearTimeout(this.timeoutId);
        this.timeoutId = browser.setTimeout(() => {
            this.state.updateSuccessful = false;
        }, 1500);
    }
}