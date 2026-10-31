import SwatEditor from '@/pages/SwatEditor';

// Mounts the full SWAT+ Editor inside the canvas pane. It manages its own field
// select and tabs, so no props are needed here (the panel is the same component
// as the /editor route).
export default function SwatEditorWidget() {
  return <SwatEditor />;
}
