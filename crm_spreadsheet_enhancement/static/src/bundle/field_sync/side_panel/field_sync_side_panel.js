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
     * 🔥 GENERIC: Get current list (CRM or Sales)
     */
    getCurrentList() {
        const fieldSync = this.fieldSync;
        if (!fieldSync) {
            return null;
        }

        const lists = this.env.model.getters.getMainLists();
        return lists.find(list => list.id === fieldSync.listId) || null;
    }

    /**
     * 🔥 GENERIC: Get current model name
     */
    get currentModelName() {
        const list = this.getCurrentList();
        return list ? list.model : null;
    }

    /**
     * 🔥 GENERIC: Get display name for current model
     */
    get modelDisplayName() {
        const models = this.env.model.getters.getSupportedModels();
        const modelName = this.currentModelName;
        return modelName && models[modelName] 
            ? models[modelName].displayName 
            : 'Record';
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
     * Filter writable fields
     */
    filterField(field) {
        return (
            !field.readonly &&
            // 🔥 GENERIC: Exclude parent field based on model
            field.name !== "order_id" &&
            field.name !== "lead_id" &&
            ["integer", "float", "monetary", "char", "text", "many2one", "boolean"].includes(
                field.type
            )
        );
    }

    updateRecordPosition(event) {
        this.updateFieldSync({ indexInList: parseInt(event.target.value) - 1 });
    }

    updateField(fieldName) {
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