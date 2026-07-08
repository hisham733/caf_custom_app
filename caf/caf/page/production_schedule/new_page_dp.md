this si new design for the page production schedule 
as in edit mode it will create new verion if there is existing pd if not it will be 0001 pd for whole week 
then add submiet button that submit will do nothink just submit and change the mode to veiw mode 
then will appear 6 create work order buttun each of each day and thet be able to click only under these two condadions 
- if its in veiw mode hwich is teh user click on submit button that in the page and the custom_submit_ref that in that dp is empty 
so if the user click on it, it will act same as create work order in pd 
 if (frm.doc.docstatus === 1 && frm.doc.workflow_state === "Submitted") {
            if (!frm.doc.custom_submit_ref) {
                frm.add_custom_button(__('Create Work Order'), function() {
                    frappe.confirm(__('This will process all production changes (Swaps, Size Changes, and Cancellations). Are you sure?'), () => {
                        show_loading_overlay();
                        frm.call({
                            doc: frm.doc,
                            method: 'process_manual_updates',
                            callback: function(r) {
                                hide_loading_overlay();
                                if(!r.exc) {
                                    frm.reload_doc();
                                    frappe.show_alert({ message: __('✅ Production updates processed successfully'), indicator: 'green' });
                                }
                            },

then when and not in background so the page can freaz untel all done then if teh user change to edit mode it will dose it job then if teh user change drag and drop add new it will run normaily as now in backgrornd job 



try to understand and discuse with me and ask q if needed after done tell me how u plane to build it make md for the work flow so i can see then when i tell u ok build u can start build 