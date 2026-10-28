import React, { useState, useEffect, useCallback } from 'react';
import {
  getDatabaseCollections,
  createDatabaseCollection,
  getCollectionDocuments,
  dropCustomCollection,
} from '../../services/api';

export default function CollectionsExplorerSection() {
  const [collections, setCollections] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  // Create Collection Modal
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newColName, setNewColName] = useState('');
  const [newColDesc, setNewColDesc] = useState('');
  const [creating, setCreating] = useState(false);

  // Document Inspector State
  const [inspectCol, setInspectCol] = useState(null);
  const [inspectDocs, setInspectDocs] = useState([]);
  const [inspectTotal, setInspectTotal] = useState(0);
  const [inspectSkip, setInspectSkip] = useState(0);
  const [inspectLimit] = useState(15);
  const [inspectLoading, setInspectLoading] = useState(false);

  const loadCollections = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getDatabaseCollections();
      setCollections(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to fetch MongoDB collections.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCollections();
  }, [loadCollections]);

  const handleCreateCollection = async (e) => {
    e.preventDefault();
    const cleanName = newColName.trim();
    if (!cleanName) {
      setError('Collection name is required.');
      return;
    }

    setCreating(true);
    setError('');
    setNotice('');

    try {
      await createDatabaseCollection(cleanName, newColDesc.trim() || null);
      setNotice(`Collection '${cleanName}' created successfully in MongoDB!`);
      setShowCreateModal(false);
      setNewColName('');
      setNewColDesc('');
      await loadCollections();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to create collection.');
    } finally {
      setCreating(false);
    }
  };

  const loadDocuments = useCallback(async (colName, skip = 0) => {
    setInspectLoading(true);
    setError('');
    try {
      const res = await getCollectionDocuments(colName, skip, inspectLimit);
      setInspectDocs(res.data.documents || []);
      setInspectTotal(res.data.total_documents || 0);
      setInspectSkip(skip);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to inspect documents.');
    } finally {
      setInspectLoading(false);
    }
  }, [inspectLimit]);

  const handleOpenInspector = (colName) => {
    setInspectCol(colName);
    loadDocuments(colName, 0);
  };

  const handleDropCollection = async (colName) => {
    const confirmed = window.confirm(`Are you sure you want to drop collection '${colName}'? This action cannot be undone.`);
    if (!confirmed) return;

    setError('');
    setNotice('');

    try {
      await dropCustomCollection(colName);
      setNotice(`Collection '${colName}' has been dropped successfully.`);
      if (inspectCol === colName) {
        setInspectCol(null);
      }
      await loadCollections();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to drop collection.');
    }
  };

  return (
    <section className="admin-panel">
      <div className="admin-panel-heading">
        <div>
          <h3>MongoDB Collections Explorer</h3>
          <p>
            Inspect, manage, and add collections in the active MongoDB Atlas cluster database.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <span className="admin-data-label">{collections.length} COLLECTIONS</span>
          <button
            type="button"
            className="admin-action-button success"
            onClick={() => {
              setError('');
              setShowCreateModal(true);
            }}
          >
            + Create Collection
          </button>
        </div>
      </div>

      {notice && <div className="admin-notice">{notice}</div>}
      {error && <div className="admin-error-banner">{error}</div>}

      {/* Create Collection Modal */}
      {showCreateModal && (
        <div className="admin-modal-backdrop">
          <div className="admin-modal-content">
            <div className="admin-modal-header">
              <h4>Create New MongoDB Collection</h4>
              <button
                type="button"
                className="admin-modal-close"
                onClick={() => setShowCreateModal(false)}
              >
                &times;
              </button>
            </div>
            <form onSubmit={handleCreateCollection}>
              <div className="admin-form-group">
                <label>Collection Name * (Letters, numbers, underscores)</label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="e.g. audit_logs or consumer_notices"
                  value={newColName}
                  onChange={(e) => setNewColName(e.target.value)}
                  pattern="^[a-zA-Z0-9_\-]+$"
                  required
                />
              </div>

              <div className="admin-form-group">
                <label>Description (Optional note)</label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="e.g. Storage for citizen notice drafts"
                  value={newColDesc}
                  onChange={(e) => setNewColDesc(e.target.value)}
                />
              </div>

              <div className="admin-modal-actions">
                <button
                  type="button"
                  className="admin-action-button"
                  onClick={() => setShowCreateModal(false)}
                  disabled={creating}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="admin-action-button success"
                  disabled={creating}
                >
                  {creating ? 'Creating...' : 'Create Collection'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Document Inspector Modal */}
      {inspectCol && (
        <div className="admin-modal-backdrop">
          <div className="admin-modal-content" style={{ maxWidth: '900px', width: '90%' }}>
            <div className="admin-modal-header">
              <div>
                <h4>
                  Collection: <span style={{ color: '#06d6a0' }}>{inspectCol}</span>
                </h4>
                <p style={{ margin: 0, fontSize: '0.82rem', color: '#888' }}>
                  Total records: {inspectTotal} &bull; Showing {inspectDocs.length} documents
                </p>
              </div>
              <button
                type="button"
                className="admin-modal-close"
                onClick={() => setInspectCol(null)}
              >
                &times;
              </button>
            </div>

            <div style={{ maxHeight: '500px', overflowY: 'auto', padding: '12px 0' }}>
              {inspectLoading ? (
                <div className="admin-loading">Loading collection documents...</div>
              ) : inspectDocs.length === 0 ? (
                <div className="admin-empty">This collection currently contains 0 documents.</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {inspectDocs.map((doc, idx) => (
                    <div
                      key={doc._id || idx}
                      style={{
                        background: '#12171f',
                        border: '1px solid rgba(255,255,255,0.08)',
                        borderRadius: '6px',
                        padding: '12px',
                        fontSize: '0.85rem',
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          marginBottom: '6px',
                          color: '#06d6a0',
                          fontWeight: 'bold',
                        }}
                      >
                        <span>Document #{inspectSkip + idx + 1}</span>
                        {doc._id && <span style={{ color: '#888' }}>_id: {doc._id}</span>}
                      </div>
                      <pre
                        style={{
                          margin: 0,
                          color: '#e2e8f0',
                          fontFamily: 'monospace',
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          maxHeight: '200px',
                          overflowY: 'auto',
                        }}
                      >
                        {JSON.stringify(doc, null, 2)}
                      </pre>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                paddingTop: '12px',
                borderTop: '1px solid rgba(255,255,255,0.08)',
              }}
            >
              <button
                type="button"
                className="admin-action-button"
                disabled={inspectSkip === 0 || inspectLoading}
                onClick={() => loadDocuments(inspectCol, Math.max(0, inspectSkip - inspectLimit))}
              >
                &larr; Previous Page
              </button>
              <span style={{ fontSize: '0.82rem', color: '#aaa' }}>
                Page {Math.floor(inspectSkip / inspectLimit) + 1} of{' '}
                {Math.ceil(inspectTotal / inspectLimit) || 1}
              </span>
              <button
                type="button"
                className="admin-action-button"
                disabled={inspectSkip + inspectLimit >= inspectTotal || inspectLoading}
                onClick={() => loadDocuments(inspectCol, inspectSkip + inspectLimit)}
              >
                Next Page &rarr;
              </button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="admin-loading">Loading database collections...</div>
      ) : collections.length === 0 ? (
        <div className="admin-empty">No collections found in this database.</div>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Collection Name</th>
                <th>Type</th>
                <th>Document Count</th>
                <th>Indexes</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {collections.map((col) => (
                <tr key={col.name}>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontSize: '1.1rem' }}>🗄</span>
                      <strong style={{ color: '#fff', fontFamily: 'monospace' }}>
                        {col.name}
                      </strong>
                    </div>
                  </td>
                  <td>
                    {col.is_system ? (
                      <span
                        style={{
                          background: 'rgba(26,107,90,0.3)',
                          color: '#06d6a0',
                          padding: '3px 8px',
                          borderRadius: '4px',
                          fontSize: '0.75rem',
                          fontWeight: '600',
                        }}
                      >
                        Core System
                      </span>
                    ) : (
                      <span
                        style={{
                          background: 'rgba(255,255,255,0.1)',
                          color: '#e2e8f0',
                          padding: '3px 8px',
                          borderRadius: '4px',
                          fontSize: '0.75rem',
                        }}
                      >
                        Custom
                      </span>
                    )}
                  </td>
                  <td>
                    <span style={{ fontWeight: 'bold', color: '#06d6a0' }}>
                      {col.document_count}
                    </span>{' '}
                    docs
                  </td>
                  <td>{col.indexes_count} indexes</td>
                  <td>
                    <div style={{ display: 'flex', gap: '6px' }}>
                      <button
                        type="button"
                        className="admin-action-button"
                        onClick={() => handleOpenInspector(col.name)}
                      >
                        Inspect Docs
                      </button>
                      {!col.is_system && (
                        <button
                          type="button"
                          className="admin-action-button danger"
                          onClick={() => handleDropCollection(col.name)}
                        >
                          Drop
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
